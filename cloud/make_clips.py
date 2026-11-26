"""Cloud clip maker (GitHub Actions): record the biggest live GTA 6 streams, cut the strongest moments, publish them
as release assets and add them to queue/manifest.json (held until the platform APIs are approved).
Run from the repository root:  python cloud/make_clips.py
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "bot"))
import approvals
import chat_signal
import kick_api as k

REPO = os.environ.get("GITHUB_REPOSITORY", "salahemd19/gta6-bot")
STREAMS = int(os.environ.get("STREAMS", "4"))
SECONDS = int(os.environ.get("CAPTURE", "600"))
PER_STREAM = int(os.environ.get("PER_STREAM", "3"))
BAD = re.compile(r"\b(fuck|shit|nigg\w*|bitch|cunt|faggot|rape|putain|merde|encul\w*|connard\w*|salope\w*|fdp|nazi\w*|viol\w*|suicid\w*)\b", re.I)
MANIFEST = Path("queue/manifest.json")
WORK = Path("work")


def sh(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def motion(path):
    """Mean frame-to-frame change (0-255). Menus, waiting rooms and seated scenes score very low."""
    r = sh("ffmpeg", "-i", str(path), "-vf", "fps=4,scale=180:-1,format=gray,tblend=all_mode=difference,signalstats,metadata=print",
           "-an", "-f", "null", "-")
    v = [float(x) for x in re.findall(r"YAVG=([\d.]+)", r.stderr)]
    return sum(v) / len(v) if v else 0.0


def capture(s):
    d = WORK / s["slug"]
    d.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        sh("yt-dlp", "--no-playlist", "-f", "best[height<=720]/best", "--downloader", "ffmpeg", "--downloader-args",
           f"ffmpeg:-t {SECONDS}", "-o", str(d / "capture.mp4"), f"https://kick.com/{s['slug']}", timeout=SECONDS + 600)
    except subprocess.TimeoutExpired:
        pass
    try:
        (d / "chat.json").write_text(json.dumps(chat_signal.fetch(s["slug"], t0, SECONDS)), encoding="utf-8")
    except Exception as e:
        print(s["slug"], "chat unavailable:", str(e)[:80])
    ok = (d / "capture.mp4").exists()
    print(s["slug"], "captured" if ok else "capture FAILED", flush=True)
    return ok


def main():
    env = {"KICK_CLIENT_ID": os.environ["KICK_CLIENT_ID"], "KICK_CLIENT_SECRET": os.environ["KICK_CLIENT_SECRET"]}
    tok = k.get_token(env)
    live = k.api_get(tok, "livestreams", category_id=13155, limit=40, sort="viewer_count").get("data", [])
    items = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    now = dt.datetime.now(dt.timezone.utc)
    recent = {i.get("streamer") for i in items if i.get("created") and
              now - dt.datetime.fromisoformat(i["created"]) < dt.timedelta(hours=3)}
    chosen = [s for s in live if s["slug"] not in recent][:STREAMS]
    print("recording:", [(s["slug"], s["viewer_count"]) for s in chosen])
    with ThreadPoolExecutor(max_workers=len(chosen) or 1) as ex:
        ok = list(ex.map(capture, chosen))

    approvals.ensure_labels()
    sh("gh", "release", "create", "clips", "--repo", REPO, "--title", "Clips", "--notes", "Clips referenced by the manifest")
    stamp = now.strftime("%Y%m%d-%H%M")
    added = 0
    for s, good in zip(chosen, ok):
        if not good:
            continue
        slug = s["slug"]
        d = (WORK / slug).resolve()
        lang = (s.get("language") or "en")[:2].lower()
        r = subprocess.run([sys.executable, str(HERE / "clipper.py"), str(d / "capture.mp4"), "--count", str(PER_STREAM),
                            "--len", "30", "--out", str(d / "clips"), "--lang", lang, "--chat", str(d / "chat.json")],
                           cwd=HERE)
        meta = d / "clips" / "clips.json"
        if r.returncode or not meta.exists():
            print(slug, "clipping failed")
            continue
        used = []  # unique scenes: never two clips sharing any footage
        for c in sorted(json.loads(meta.read_text(encoding="utf-8")), key=lambda x: -x["score"]):
            if any(c["start"] < e and c["end"] > s0 for s0, e in used):
                print(slug, c["file"], "rejected (overlaps another clip)")
                continue
            used.append((c["start"], c["end"]))
            f = d / "clips" / c["file"]
            m = motion(f)
            if m < 11.0 or BAD.search(c["transcript"]):
                print(slug, c["file"], f"rejected (motion {m:.1f} or language)")
                continue
            name = f"{stamp}-{slug}-{c['file']}"
            asset = f.with_name(name)
            f.rename(asset)
            up = sh("gh", "release", "upload", "clips", str(asset), "--repo", REPO, "--clobber")
            if up.returncode:
                print("upload failed:", up.stderr[-200:])
                continue
            title = f"{c['hook']} 😱 {slug} sur GTA 6"
            caption = f"{title} #GTA6 #GTAVI #{slug.replace('_', '')} #Kick #pourtoi #fyp"
            items.append({
                "id": name[:-4], "streamer": slug, "created": now.isoformat(timespec="seconds"),
                "video_url": f"https://github.com/{REPO}/releases/download/clips/{name}",
                "title": title[:95], "youtube_description": f"Clip du live de {slug} sur Kick.\n\n#GTA6 #GTAVI #Shorts",
                "tiktok_caption": caption, "youtube_privacy": "public", "score": c["score"], "motion": round(m, 1),
                "slot": now.isoformat(timespec="seconds"),
                "youtube": "awaiting approval", "tiktok": "awaiting approval"})
            try:
                items[-1]["issue"] = approvals.open_issue(items[-1])
            except Exception as e:  # noqa: BLE001
                print("issue not created:", e)
            added += 1
    MANIFEST.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
    print("clips added:", added)


if __name__ == "__main__":
    main()
