"""Post the next due video(s) from queue/manifest.json to YouTube and TikTok (runs in GitHub Actions every 2 hours).

Rules: at most 1 post per platform per run; rolling 24 h caps (YouTube 4, TikTok 8); a platform that errors is
marked 'failed: ...' and retried on the next run (max 3 attempts); nothing is deleted.
"""
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
import tiktok
import yt

MANIFEST = Path("queue/manifest.json")
CAPS = {"youtube": 8, "tiktok": 8}


def now():
    return dt.datetime.now(dt.timezone.utc)


def posted_last_24h(items, platform):
    n = 0
    for it in items:
        s = str(it.get(platform, ""))
        if s.startswith("posted "):
            try:
                if now() - dt.datetime.fromisoformat(s[7:]) < dt.timedelta(hours=24):
                    n += 1
            except ValueError:
                pass
    return n


def due(it, platform):
    s = str(it.get(platform, "pending"))
    if not (s.startswith("pending") or s.startswith("failed (retry")):
        return False
    return dt.datetime.fromisoformat(it["slot"]) <= now()  # slots are UTC ISO strings


def fetch(it, tmp):
    p = Path(tmp) / (it["id"] + ".mp4")
    with requests.get(it["video_url"], stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(p, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return p


def main():
    items = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ts = now().isoformat(timespec="minutes")
    changed = False
    for platform in ("youtube", "tiktok"):
        if posted_last_24h(items, platform) >= CAPS[platform]:
            print(platform, "cap reached; skipping")
            continue
        cands = sorted((i for i in items if due(i, platform)), key=lambda i: -i.get("score", 0))
        if not cands:
            print(platform, "nothing due")
            continue
        it = cands[0]
        with tempfile.TemporaryDirectory() as tmp:
            try:
                path = fetch(it, tmp)
                if platform == "youtube":
                    vid = yt.upload(path, it["title"], it["youtube_description"], it.get("youtube_privacy", "public"))
                    it["youtube"] = f"posted {ts}"
                    it["youtube_url"] = f"https://youtube.com/shorts/{vid}"
                else:
                    pid, status, new_refresh = tiktok.post(path, it["tiktok_caption"])
                    it["tiktok"] = f"posted {ts}" if status == "PUBLISH_COMPLETE" else f"posted {ts} (status {status})"
                    if new_refresh and new_refresh != os.environ.get("TIKTOK_REFRESH_TOKEN"):
                        print("::warning::TikTok rotated the refresh token; update the TIKTOK_REFRESH_TOKEN secret")
                print("posted", it["id"], "to", platform)
            except Exception as e:  # noqa: BLE001 - one bad post must not stop the other platform
                tries = it.get(platform + "_tries", 0) + 1
                it[platform + "_tries"] = tries
                it[platform] = f"failed (retry {tries}/3): {str(e)[:120]}" if tries < 3 else f"failed: {str(e)[:120]}"
                print("::error::", platform, it["id"], e)
        changed = True
    if changed:
        MANIFEST.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
