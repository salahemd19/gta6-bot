"""Can a GitHub runner reach Kick? Checks the official API, the stream capture and the chat history."""
import os
import subprocess
import sys
import time

import kick_api as k
import chat_signal

env = {"KICK_CLIENT_ID": os.environ["KICK_CLIENT_ID"], "KICK_CLIENT_SECRET": os.environ["KICK_CLIENT_SECRET"]}
tok = k.get_token(env)
live = k.api_get(tok, "livestreams", category_id=13155, limit=5, sort="viewer_count").get("data", [])
print("1) official API OK:", [(s["slug"], s["viewer_count"]) for s in live])
slug = live[0]["slug"]
t0 = time.time()
r = subprocess.run(["yt-dlp", "--no-playlist", "-f", "best[height<=720]/best", "--downloader", "ffmpeg",
                    "--downloader-args", "ffmpeg:-t 30", "-o", "cap.mp4", f"https://kick.com/{slug}"],
                   capture_output=True, text=True, timeout=400)
ok = os.path.exists("cap.mp4")
print("2) capture:", "OK %.1f MB" % (os.path.getsize("cap.mp4") / 1e6) if ok else "FAILED " + r.stderr[-600:])
try:
    c = chat_signal.fetch(slug, t0 - 60, 30)
    print("3) chat history OK:", len(c["offsets"]), "messages")
except Exception as e:
    print("3) chat history FAILED:", str(e)[:200])
sys.exit(0 if ok else 1)
