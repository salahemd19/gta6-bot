"""Approvals on Telegram: each new video is sent to the owner with Publier / Rejeter buttons, and the answer is applied.

  python cloud/telegram_bot.py run [--listen 50]     send new requests, then handle answers
Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (set by tools/connect_telegram.py), GH_TOKEN.

Only the owner's own chat is obeyed. The decision is written to the video's GitHub issue (label approved or rejected),
so GitHub stays the single record. Commands: /statut, /pause, /reprendre, /aide.
"""
import argparse
import datetime as dt
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publisher as P  # noqa: E402

OVERRIDES = P.ROOT / "config" / "overrides.json"
REPO = os.environ.get("GITHUB_REPOSITORY", "salahemd19/gta6-bot")
MAX_UPLOAD = 49 * 1024 * 1024
HELP = ("Boutons sous chaque vidéo : ✅ Publier ou ❌ Rejeter.\n/statut : programme du jour et vidéos en attente\n"
        "/pause : arrête toute l'automatisation\n/reprendre : la relance")


def configured():
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def owner():
    return str(os.environ["TELEGRAM_CHAT_ID"]).strip()


def call(method, files=None, http_timeout=120, **data):
    """One Bot API call. Errors never carry the address, because the address contains the token."""
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN'].strip()}/{method}"
    try:
        body = requests.post(url, data=data, files=files, timeout=http_timeout).json()
    except (requests.RequestException, ValueError) as e:
        raise RuntimeError(f"Telegram {method}: {type(e).__name__}") from None
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method}: {body.get('description')}")
    return body["result"]


def send(text, **extra):
    return call("sendMessage", chat_id=owner(), text=text[:4000], **extra)


def buttons(issue):
    return json.dumps({"inline_keyboard": [[{"text": "✅ Publier", "callback_data": f"ok:{issue}"},
                                            {"text": "❌ Rejeter", "callback_data": f"no:{issue}"}]]})


def waiting(item):
    return any(P.kind(item.get(p)) == "review" for p in P.PLATFORMS)


def caption(item):
    lines = [f"🎬 {item.get('title', item['id'])}", f"Créateurs : {item.get('streamer', '?')}"]
    if item.get("category"):
        lines.append(f"Catégorie : {item['category']}")
    if item.get("duration_s"):
        lines.append(f"Durée : {item['duration_s']:.0f} s")
    lines.append(f"https://github.com/{REPO}/issues/{item['issue']}")
    return "\n".join(lines)[:1000]


def fetch(url, folder):
    path = Path(folder) / "video.mp4"
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return path


def send_requests(limit=4):
    """Send every video that still waits for a decision and was not sent yet."""
    sent = []
    todo = [i for i in P.load(P.MANIFEST, []) if i.get("issue") and not i.get("tg") and waiting(i)][-limit:]
    for item in todo:
        with tempfile.TemporaryDirectory() as tmp:
            video = fetch(item["video_url"], tmp)
            if video.stat().st_size <= MAX_UPLOAD:
                with open(video, "rb") as f:
                    msg = call("sendVideo", files={"video": (f"{item['id']}.mp4", f, "video/mp4")}, chat_id=owner(),
                               caption=caption(item), reply_markup=buttons(item["issue"]), supports_streaming="true",
                               http_timeout=600)
            else:
                msg = send(caption(item) + f"\nVidéo : {item['video_url']}", reply_markup=buttons(item["issue"]))
        items = P.load(P.MANIFEST, [])  # re-read: keep whatever changed while uploading
        next(i for i in items if i["id"] == item["id"])["tg"] = msg["message_id"]
        P.save(P.MANIFEST, items)
        sent.append(item["issue"])
    return sent


def label(issue, approve):
    """Record the decision on the GitHub issue."""
    h = {"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"}
    api = f"https://api.github.com/repos/{REPO}/issues/{issue}"
    requests.post(f"{api}/labels", headers=h, json={"labels": ["approved" if approve else "rejected"]}, timeout=30).raise_for_status()
    requests.post(f"{api}/comments", headers=h, timeout=30,
                  json={"body": f"Décision reçue par Telegram : {'publier' if approve else 'rejeter'}."}).raise_for_status()
    if not approve:
        requests.patch(api, headers=h, json={"state": "closed"}, timeout=30).raise_for_status()


def paris(iso):
    return dt.datetime.fromisoformat(iso).astimezone(P.tz()).strftime("%d/%m à %H:%M")


def decide(issue, approve):
    """Apply one decision and return the answer to show the owner."""
    items = P.load(P.MANIFEST, [])
    item = next((i for i in items if i.get("issue") == issue), None)
    if not item:
        return f"Vidéo {issue} introuvable."
    if not waiting(item):
        return f"Vidéo {issue} déjà traitée (YouTube : {item.get('youtube')}, TikTok : {item.get('tiktok')})."
    label(issue, approve)
    for p in P.PLATFORMS:
        if P.kind(item.get(p)) == "review":
            item[p] = "pending" if approve else "rejected by owner"
    P.save(P.MANIFEST, items)
    P.plan()
    if not approve:
        return f"❌ Vidéo {issue} rejetée."
    item = next(i for i in P.load(P.MANIFEST, []) if i.get("issue") == issue)
    slots = [f"{n} : {paris(item[f'slot_{p}'])}" if item.get(f"slot_{p}") else f"{n} : pas encore de créneau"
             for p, n in (("youtube", "YouTube"), ("tiktok", "TikTok"))]
    return f"✅ Vidéo {issue} approuvée.\n" + "\n".join(slots)


def status():
    cal = P.plan(dry=True)
    lines = ["Aujourd'hui :"]
    for p, c in cal["platforms"].items():
        rows = [r for r in c["days"][0]["slots"] if r["id"]]
        lines.append(f"{p.title()} ({len(rows)}/{c['cap']})")
        lines += [f"  {r['local']} {r['status']} {str(r['title'])[:40]}" for r in rows]
    pend = sorted({w["issue"] for w in cal["waiting_approval"] if w.get("issue")})
    lines.append(f"En attente de ta décision : {', '.join(map(str, pend)) or 'rien'}")
    if P.load(OVERRIDES, {}).get("paused"):
        lines.append("⏸ Automatisation en pause.")
    return "\n".join(lines)


def pause(on):
    o = P.load(OVERRIDES, {"disabled_jobs": [], "note": ""})
    o["paused"], o["note"] = on, "demandé par Telegram" if on else ""
    P.save(OVERRIDES, o)
    return "⏸ Tout est en pause. Les posts déjà programmés dans les applis partiront quand même." if on else "▶️ Automatisation relancée."


def handle(update):
    """One update from Telegram. Anything not coming from the owner's chat is ignored."""
    cq = update.get("callback_query")
    if cq:
        msg = cq.get("message") or {}
        if str(cq.get("from", {}).get("id")) != owner() or str(msg.get("chat", {}).get("id")) != owner():
            return None
        action, _, number = str(cq.get("data", "")).partition(":")
        if action not in ("ok", "no") or not number.isdigit():
            return None
        answer = decide(int(number), action == "ok")
        for method, extra in (("answerCallbackQuery", {"callback_query_id": cq["id"], "text": answer[:190]}),
                              ("editMessageReplyMarkup", {"chat_id": owner(), "message_id": msg.get("message_id"),
                                                          "reply_markup": json.dumps({"inline_keyboard": []})})):
            try:
                call(method, **extra)
            except RuntimeError as e:  # an old button press can no longer be acknowledged; the decision is applied anyway
                print(e)
        send(answer, reply_to_message_id=msg.get("message_id"))
        return answer
    msg = update.get("message") or {}
    if str(msg.get("chat", {}).get("id")) != owner():
        return None
    words = str(msg.get("text", "")).strip().lower().split()
    if not words:
        return None
    if words[0] in ("ok", "non") and len(words) == 2 and words[1].isdigit():
        answer = decide(int(words[1]), words[0] == "ok")
    elif words[0] in ("/statut", "/status"):
        answer = status()
    elif words[0] in ("/pause", "/reprendre"):
        answer = pause(words[0] == "/pause")
    else:
        answer = HELP
    send(answer)
    return answer


def handle_updates(listen=0):
    """Read pending answers (waiting up to `listen` seconds). An update is confirmed only after it was applied."""
    done, end = [], time.time() + listen
    while True:
        wait = max(0, min(50, int(end - time.time())))
        updates = call("getUpdates", http_timeout=wait + 30, timeout=wait,
                       allowed_updates=json.dumps(["message", "callback_query"]))
        next_offset, failed = None, None
        for u in updates:
            try:
                a = handle(u)
                if a:
                    done.append(a)
                next_offset = u["update_id"] + 1
            except Exception as e:  # noqa: BLE001 - leave it unconfirmed so the next run tries again
                failed = e
                break
        if next_offset:
            call("getUpdates", offset=next_offset, limit=1)
        if failed:
            raise RuntimeError(f"could not apply an answer: {failed}")
        if time.time() >= end:
            return done
        if not updates:
            time.sleep(3)


def run(listen=0):
    if not configured():
        return "not connected (run tools/connect_telegram.py)"
    sent = send_requests()
    answers = handle_updates(listen)
    return f"sent {sent or 'nothing'}; {len(answers)} answers applied"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--listen", type=int, default=0)
    a = ap.parse_args()
    print(run(a.listen))


if __name__ == "__main__":
    main()
