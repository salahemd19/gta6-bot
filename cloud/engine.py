"""VICECITY INTEL content engine: DISCOVER -> ANALYSE -> SCORE -> SELECT -> PRODUCE -> PACKAGE -> REVIEW.

One central database (db/clips.json) records every candidate: source, creator, URLs, timestamps, metrics, scores,
authenticity, rights, duplicate links, editing status and publication history. Publishing itself is done by
bot/post_next.py (cloud, once the APIs are approved) or the laptop task, and only after the owner approves the issue.

Run from the repo root:  python cloud/engine.py [--discover-only] [--max-analyse 40] [--videos 1]
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "music"))
import montage  # noqa: E402
from clipper import visual  # noqa: E402

DB = ROOT / "db" / "clips.json"
MANIFEST = ROOT / "queue" / "manifest.json"
WORK = ROOT / "work" / "engine"
REPO = os.environ.get("GITHUB_REPOSITORY", "salahemd19/gta6-bot")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"}
KICK_CLIPS = "https://kick.com/api/v2/categories/grand-theft-auto-vi/clips"
SEG = 6.5

PILLARS = {
    "VIRAL MOMENTS & CHAOS": r"wtf|lol|xd|kkk|jaja|chaos|crazy|fou|insane|ptdr|😂|💀",
    "RACING & VEHICLES": r"car|race|drift|moto|bike|voiture|course|plane|avion|boat|bateau|heli",
    "CHALLENGES & EXPERIMENTS": r"challenge|défi|test|experiment|1v1|vs",
    "MAP & SECRET DISCOVERIES": r"secret|easter|hidden|caché|map|carte|found|trouvé",
    "CHEATS, TIPS & MONEY": r"cheat|money|argent|tip|astuce|glitch|bank|braquage|heist|robbery",
    "LEONIDA LIFE & DETAILS": r"detail|npc|beach|plage|life|vie|animal|weather",
}
TITLES = {  # French hooks per format; the engine rotates them and never repeats the last one used
    "top3": ["TOP 3 MOMENTS LES PLUS FOUS SUR GTA 6", "3 MOMENTS IRRÉELS VUS EN LIVE SUR GTA 6",
             "LE TOP 3 GTA 6 DU JOUR", "ILS ONT FAIT ÇA SUR GTA 6 (TOP 3)"],
}


# ---------------------------------------------------------------- database
def load_db():
    return json.loads(DB.read_text(encoding="utf-8")) if DB.exists() else {}


def save_db(db):
    DB.parent.mkdir(exist_ok=True)
    DB.write_text(json.dumps(db, indent=1, ensure_ascii=False), encoding="utf-8")


def now():
    return dt.datetime.now(dt.timezone.utc)


def log(stage, msg):
    print(f"[{now().strftime('%H:%M:%S')}] {stage}: {msg}", flush=True)


# ---------------------------------------------------------------- discover
def discover(db, pages=4):
    """Kick viewer clips for the GTA 6 category (most viewed today and this week). Records new ones; dedupes by id."""
    new = 0
    for t in ("day", "week"):
        cur = None
        for _ in range(pages):
            p = {"sort": "view", "time": t}
            if cur:
                p["cursor"] = cur
            for attempt in range(3):  # retries with backoff
                try:
                    r = requests.get(KICK_CLIPS, params=p, headers=UA, timeout=30)
                    r.raise_for_status()
                    data = r.json()
                    break
                except Exception as e:  # noqa: BLE001
                    log("discover", f"retry {attempt + 1}: {e}")
                    time.sleep(3 * (attempt + 1))
            else:
                break
            for c in data.get("clips", []):
                cid = c["id"]
                slug = (c.get("channel") or {}).get("slug") or str(c.get("channel_id"))
                if cid in db:
                    db[cid]["views"] = c.get("views", db[cid].get("views"))  # keep metrics fresh
                    continue
                db[cid] = {
                    "id": cid, "source": "kick", "creator": slug, "channel_id": c.get("channel_id"),
                    "livestream_id": c.get("livestream_id"), "title": c.get("title", ""),
                    "url": f"https://kick.com/{slug}/clips/{cid}", "media_url": c.get("clip_url"),
                    "thumbnail": c.get("thumbnail_url"), "views": c.get("views", 0),
                    "duration": c.get("duration", 0), "created_at": c.get("created_at"),
                    "vod_starts_at": c.get("vod_starts_at"), "is_mature": c.get("is_mature"),
                    "discovered_at": now().isoformat(timespec="seconds"),
                    "status": "discovered", "authenticity": "unchecked", "rights": "credited_third_party",
                    "used_in": [], "duplicate_of": None,
                }
                new += 1
            cur = data.get("nextCursor")
            if not cur:
                break
    log("discover", f"{new} new clips, {len(db)} in database")
    return new


# ---------------------------------------------------------------- analyse + score
def dhash(path, at):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1", "-vf",
                        "scale=9:8,format=gray", "-f", "rawvideo", "-"], capture_output=True)
    px = np.frombuffer(r.stdout, dtype=np.uint8)
    if px.size != 72:
        return None
    px = px.reshape(8, 9).astype(int)
    return "".join("1" if b else "0" for b in (px[:, 1:] > px[:, :-1]).flatten())


def audio_peak(path, length=SEG):
    a = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
                       capture_output=True).stdout
    au = np.frombuffer(a, dtype=np.float32)
    if au.size < 8000:
        return 0.0, 0.0, 0.0
    step = 2000  # 0.25 s
    n = au.size // step
    rms = np.sqrt((au[: n * step].reshape(n, step) ** 2).mean(axis=1))
    w = int(length * 4)
    if n <= w:
        return 0.0, float(rms.max() / (rms.mean() + 1e-9)), float(rms.mean())
    jump = np.clip(np.diff(rms, prepend=rms[0]), 0, None)
    s = rms / (rms.mean() + 1e-9) + 2 * jump / (rms.mean() + 1e-9)
    cs = np.concatenate([[0], np.cumsum(s)])
    i = int(np.argmax(cs[w:] - cs[:-w]))
    return i / 4, float(rms.max() / (rms.mean() + 1e-9)), float(rms.mean())


def pillar_of(title):
    t = (title or "").lower()
    for p, rx in PILLARS.items():
        if re.search(rx, t):
            return p, "keyword"
    return "VIRAL MOMENTS & CHAOS", "default"


def score(rec):
    """Measurable signals only, 0-10 each. Dimensions that need understanding of the scene (storytelling, real
    originality) are left None until a vision model is connected; the human review covers them."""
    m = rec["metrics"]
    age_h = max(1.0, (now() - dt.datetime.fromisoformat(rec["created_at"].replace("Z", "+00:00"))).total_seconds() / 3600)
    velocity = rec.get("views", 0) / age_h
    s = {
        "visual_impact": round(min(10, m["motion"] / 3), 1),
        "emotional_impact": round(min(10, 2 * m["audio_crest"]), 1),
        "entertainment": round(min(10, (m["motion"] / 3 + 2 * m["audio_crest"]) / 2), 1),
        "share_potential": round(min(10, 2.2 * math.log10(1 + velocity)), 1),
        "replayability": round(10 if rec["duration"] <= 20 else 7 if rec["duration"] <= 40 else 4, 1),
        "french_relevance": 8.0 if re.search(r"\b(le|la|les|un|une|des|wesh|ptdr|mdr|frère)\b", rec["title"].lower()) else 5.0,
        "storytelling": None, "originality": None,
    }
    w = {"visual_impact": .3, "entertainment": .25, "emotional_impact": .15, "share_potential": .15,
         "replayability": .1, "french_relevance": .05}
    s["total"] = round(sum(s[k] * v for k, v in w.items()), 2)
    return s


def analyse(db, limit):
    todo = [r for r in db.values() if r["status"] == "discovered" and r["duration"] <= 65][:limit]
    hashes = {r["id"]: r["dhash"] for r in db.values() if r.get("dhash")}
    (WORK / "src").mkdir(parents=True, exist_ok=True)
    for rec in todo:
        f = WORK / "src" / f"{rec['id']}.mp4"
        try:
            if not f.exists():
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", rec["media_url"], "-t", "65", "-c", "copy", str(f)],
                               timeout=240, check=True)
            v = visual(f, 0, min(rec["duration"], 60))
            peak, crest, loud = audio_peak(f)
            h = dhash(f, min(rec["duration"] / 2, 30))
            rec["metrics"] = {**v, "peak_start": round(peak, 2), "audio_crest": round(crest, 2), "loudness": round(loud, 4)}
            rec["dhash"] = h
            rec["pillar"], rec["pillar_method"] = pillar_of(rec["title"])
            dup = next((k for k, hh in hashes.items() if h and hh and k != rec["id"]
                        and sum(a != b for a, b in zip(h, hh)) <= 6), None)
            if dup:
                rec["duplicate_of"], rec["status"] = dup, "rejected_duplicate"
            elif v["motion"] < 13 or v["still"] > 0.15 or v["letterbox"] > 0.3:
                rec["status"] = "rejected_auto"
                rec["reject_reason"] = f"motion {v['motion']}, still {v['still']}, letterbox {v['letterbox']}"
            else:
                rec["scores"] = score(rec)
                rec["status"] = "analysed"
            if h:
                hashes[rec["id"]] = h
            rec["analysed_at"] = now().isoformat(timespec="seconds")
            log("analyse", f"{rec['creator']} {rec['id'][-6:]} -> {rec['status']} {rec.get('scores', {}).get('total', '')}")
        except Exception as e:  # noqa: BLE001 - one bad clip never stops the run
            rec["status"], rec["error"] = "error", str(e)[:200]
            log("analyse", f"{rec['id']} failed: {e}")


# ---------------------------------------------------------------- select + produce + package
def select(db, k=3):
    pool = sorted((r for r in db.values() if r["status"] == "analysed" and not r["used_in"]),
                  key=lambda r: -r["scores"]["total"])
    chosen, creators = [], set()
    for r in pool:
        if r["creator"] in creators:
            continue
        chosen.append(r)
        creators.add(r["creator"])
        if len(chosen) == k:
            break
    return chosen


def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def produce(db, items, vid_id):
    chosen = select(db)
    if len(chosen) < 3:
        log("produce", f"only {len(chosen)} strong unused clips; nothing produced")
        return None
    used_titles = [i.get("title", "") for i in items[-6:]]
    title = next((t for t in TITLES["top3"] if not any(t in u for u in used_titles)), TITLES["top3"][0])
    moments = [{"slug": r["creator"], "video": str((WORK / "src" / f"{r['id']}.mp4").resolve()),
                "start": max(0.0, min(r["metrics"]["peak_start"], r["duration"] - SEG)), "len": SEG,
                "score": 10 - i} for i, r in enumerate(chosen)]
    work = (WORK / vid_id).resolve()
    work.mkdir(parents=True, exist_ok=True)
    font = ROOT / "cloud" / "fonts" / "Anton-Regular.ttf"
    if font.exists():
        (work / font.name).write_bytes(font.read_bytes())
    full = (WORK / f"{vid_id}_full.mp4").resolve()
    used = montage.render(moments, title, full, work, ".")
    out = (WORK / f"{vid_id}.mp4").resolve()
    sh("ffmpeg", "-v", "error", "-y", "-i", str(full), "-c:v", "libx264", "-preset", "slow", "-b:v", "2100k",
       "-maxrate", "2600k", "-bufsize", "4200k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
       "-movflags", "+faststart", str(out))
    sheet = (WORK / f"{vid_id}_sheet.jpg").resolve()
    sh("ffmpeg", "-v", "error", "-y", "-i", str(out), "-vf", "fps=1,scale=150:-2,tile=10x2", "-frames:v", "1", str(sheet))
    if not out.exists():
        log("produce", "render failed")
        return None
    order = [u["slug"] for u in used]
    for r in chosen:
        r["used_in"].append(vid_id)
        r["status"] = "produced"
    # music recommendation from the library (never repeats the last tracks)
    try:
        import recommend
        rec_yt = recommend.recommend("chaos", "youtube", 20, "high")
        rec_tt = recommend.recommend("chaos", "tiktok", 20, "high")
    except Exception as e:  # noqa: BLE001
        rec_yt = rec_tt = []
        log("music", f"recommender unavailable: {e}")
    credits = ", ".join(order)
    pkg = {
        "title": f"{title} 🤯 le numéro 1 est irréel",
        "youtube_description": (f"Les moments les plus fous vus en live sur GTA 6 🤯 Ton préféré ? Dis-le en commentaire 👇\n"
                                f"🎥 Créateurs (Kick) : {credits}\nAbonne-toi pour un top GTA 6 chaque jour 🔔\n\n"
                                "#GTA6 #GTAVI #GTA6FR #ViceCity #gta #Shorts"),
        "tiktok_caption": (f"{title} 🤯 le numéro 1 est irréel 😱 Ton préféré ? Dis-le en commentaire 👇 "
                           f"🎥 {credits} (Kick) #GTA6 #GTA6FR #GTAVI #gta #pourtoi #fyp"),
        "tags": "GTA 6, GTA VI, GTA 6 FR, top 3 GTA 6, GTA 6 moments fous, GTA 6 gameplay, Vice City",
        "music_youtube": [r["track"] for r in rec_yt], "music_tiktok": [r["track"] for r in rec_tt],
        "sources": [{"creator": r["creator"], "url": r["url"], "start": m["start"], "score": r["scores"]["total"]}
                    for r, m in zip(chosen, moments)],
    }
    return out, sheet, pkg, chosen


def publish_package(items, vid_id, out, sheet, pkg, chosen):
    sh("gh", "release", "create", "clips", "--repo", REPO, "--title", "Clips", "--notes", "Clips referenced by the manifest")
    for f in (out, sheet):
        up = sh("gh", "release", "upload", "clips", str(f), "--repo", REPO, "--clobber")
        if up.returncode:
            raise RuntimeError("upload failed: " + up.stderr[-200:])
    base = f"https://github.com/{REPO}/releases/download/clips/"
    entry = {"id": vid_id, "type": "top3", "created": now().isoformat(timespec="seconds"),
             "video_url": base + out.name, "sheet_url": base + sheet.name, "title": pkg["title"],
             "youtube_description": pkg["youtube_description"], "tiktok_caption": pkg["tiktok_caption"],
             "tags": pkg["tags"], "music": {"youtube": pkg["music_youtube"], "tiktok": pkg["music_tiktok"]},
             "sources": pkg["sources"], "streamer": ",".join(s["creator"] for s in pkg["sources"]),
             "score": round(sum(r["scores"]["total"] for r in chosen) / len(chosen), 2),
             "rights": "credited_third_party", "authenticity": "needs_review",
             "slot": now().isoformat(timespec="seconds"),
             "youtube": "awaiting approval", "tiktok": "awaiting approval"}
    try:
        import approvals
        approvals.ensure_labels()
        entry["issue"] = approvals.open_issue({**entry, "video_url": entry["video_url"] + "\n\n![planche](" + entry["sheet_url"] + ")"
                                               + "\n\nÀ vérifier : c'est bien GTA 6 (pas GTA V / FiveM), aucune cinématique d'histoire."
                                               + "\n\nMusique YouTube : " + ", ".join(pkg["music_youtube"])
                                               + "\nMusique TikTok (son in-app) : " + ", ".join(pkg["music_tiktok"])})
    except Exception as e:  # noqa: BLE001
        log("review", f"issue not created: {e}")
    items.append(entry)
    log("package", f"{vid_id} queued for approval (issue {entry.get('issue')})")
    return entry


def feedback(db, items):
    """Owner decisions on GitHub issues flow back into the database: clips in a rejected video are marked
    rejected_review (never reused, and they teach us what not to pick); clips in an approved video are trusted."""
    try:
        import approvals
        dec = approvals.decisions()
    except Exception as e:  # noqa: BLE001
        log("feedback", f"unavailable: {e}")
        return
    by_url = {r["url"]: r for r in db.values()}
    n = 0
    for it in items:
        d = dec.get(it.get("issue"))
        if not d or it.get("feedback_applied"):
            continue
        for s in it.get("sources", []):
            r = by_url.get(s.get("url"))
            if r:
                r["status"] = "approved" if d == "approved" else "rejected_review"
                r["review_reason"] = f"owner {d} {it['id']}"
                n += 1
        it["feedback_applied"] = d
    log("feedback", f"{n} clips updated from owner decisions")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover-only", action="store_true")
    ap.add_argument("--max-analyse", type=int, default=40)
    ap.add_argument("--videos", type=int, default=1)
    ap.add_argument("--no-publish-package", action="store_true", help="produce locally without uploading or opening issues")
    a = ap.parse_args()
    db = load_db()
    discover(db)
    save_db(db)
    if a.discover_only:
        return
    analyse(db, a.max_analyse)
    save_db(db)
    items = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else []
    feedback(db, items)
    for n in range(a.videos):
        vid_id = f"engine-{now().strftime('%Y%m%d-%H%M')}-{n + 1}"
        res = produce(db, items, vid_id)
        if not res:
            break
        out, sheet, pkg, chosen = res
        if a.no_publish_package:
            log("package", json.dumps(pkg, ensure_ascii=False)[:600])
        else:
            publish_package(items, vid_id, out, sheet, pkg, chosen)
        save_db(db)
    MANIFEST.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
    st = {}
    for r in db.values():
        st[r["status"]] = st.get(r["status"], 0) + 1
    log("summary", json.dumps(st))


if __name__ == "__main__":
    main()
