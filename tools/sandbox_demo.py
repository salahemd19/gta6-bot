"""Sandbox demo: exchange the authorisation code, show the connected account, upload and post a video.
  python tools/sandbox_demo.py <env_file> <code> <video.mp4>
"""
import sys
import time

import requests

API = "https://open.tiktokapis.com"
env = dict(l.strip().split("=", 1) for l in open(sys.argv[1], encoding="utf-8") if "=" in l)
key, secret = env["TIKTOK_SANDBOX_KEY"], env["TIKTOK_SANDBOX_SECRET"]
code, path = sys.argv[2], sys.argv[3]
redirect = "https://salahemd19.github.io/gta6-bot/callback.html"

print("1) Exchanging the authorisation code (Login Kit)...")
t = requests.post(f"{API}/v2/oauth/token/", data={"client_key": key, "client_secret": secret, "code": code,
                  "grant_type": "authorization_code", "redirect_uri": redirect}, timeout=30).json()
if "access_token" not in t:
    print("token error:", {k: v for k, v in t.items() if k != "access_token"})
    sys.exit(1)
tok = t["access_token"]
print("   authorised; scopes granted:", t.get("scope"))
h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8"}

print("2) Reading the connected account (user.info.basic)...")
u = requests.get(f"{API}/v2/user/info/?fields=open_id,display_name", headers=h, timeout=30).json()
print("  ", u.get("data", {}).get("user", u))

print("3) Querying creator info (Content Posting API)...")
c = requests.post(f"{API}/v2/post/publish/creator_info/query/", headers=h, timeout=30).json()
opts = c.get("data", {}).get("privacy_level_options", ["SELF_ONLY"])
print("   privacy options:", opts)

import os
size = os.path.getsize(path)
print(f"4) Uploading {os.path.basename(path)} ({size/1e6:.1f} MB) and publishing with a caption...")
priv = "SELF_ONLY" if "SELF_ONLY" in opts else opts[0]
body = {"post_info": {"title": "Demo: GTA VI montage (official Rockstar footage) #GTA6", "privacy_level": priv,
                      "video_cover_timestamp_ms": 1000},
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}}
init = requests.post(f"{API}/v2/post/publish/video/init/", json=body, headers=h, timeout=60).json()
if "data" not in init or "upload_url" not in init.get("data", {}):
    print("   direct post is limited until audit:", init.get("error", {}).get("code"))
    print("   -> using the upload-to-inbox flow (video.upload scope)")
    ib = {"source_info": body["source_info"]}
    init = requests.post(f"{API}/v2/post/publish/inbox/video/init/", json=ib, headers=h, timeout=60).json()
if "data" not in init or "upload_url" not in init.get("data", {}):
    print("   init response:", init)
    sys.exit(1)
pid, url = init["data"]["publish_id"], init["data"]["upload_url"]
with open(path, "rb") as f:
    data = f.read()
r = requests.put(url, data=data, headers={"Content-Type": "video/mp4", "Content-Length": str(size),
                 "Content-Range": f"bytes 0-{size-1}/{size}"}, timeout=600)
print("   upload HTTP", r.status_code)
for _ in range(12):
    s = requests.post(f"{API}/v2/post/publish/status/fetch/", json={"publish_id": pid}, headers=h, timeout=30).json()
    st = s.get("data", {}).get("status", "UNKNOWN")
    print("   publish status:", st)
    if st in ("PUBLISH_COMPLETE", "FAILED", "SEND_TO_USER_INBOX"):
        break
    time.sleep(5)
print("Done. publish_id =", pid)
