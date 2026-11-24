"""TikTok posting through the official Content Posting API (FILE_UPLOAD, direct post).

Env: TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN
Until TikTok approves the app's Direct Post audit, posts are limited to private visibility; the app must also be
authorised once by the account owner (tools/tiktok_auth.py).
"""
import os
import time
import requests

API = "https://open.tiktokapis.com"
CHUNK = 10 * 1024 * 1024


def refresh():
    r = requests.post(f"{API}/v2/oauth/token/", data={
        "client_key": os.environ["TIKTOK_CLIENT_KEY"], "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
        "grant_type": "refresh_token", "refresh_token": os.environ["TIKTOK_REFRESH_TOKEN"]}, timeout=30)
    r.raise_for_status()
    d = r.json()
    return d["access_token"], d.get("refresh_token")  # TikTok may rotate the refresh token: store the new one


def post(path, caption, privacy="PUBLIC_TO_EVERYONE"):
    """Upload `path` and publish it. Returns (publish_id, final_status, new_refresh_token)."""
    token, new_refresh = refresh()
    size = os.path.getsize(path)
    chunk = min(CHUNK, size)
    total = max(1, size // chunk)
    body = {"post_info": {"title": caption[:2200], "privacy_level": privacy, "disable_duet": False,
                          "disable_comment": False, "disable_stitch": False, "video_cover_timestamp_ms": 1000},
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": total}}
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    init = requests.post(f"{API}/v2/post/publish/video/init/", json=body, headers=h, timeout=60)
    init.raise_for_status()
    data = init.json()["data"]
    publish_id, upload_url = data["publish_id"], data["upload_url"]
    with open(path, "rb") as f:
        start = 0
        for i in range(total):
            end = size if i == total - 1 else start + chunk
            part = f.read(end - start)
            r = requests.put(upload_url, data=part, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(part)),
                "Content-Range": f"bytes {start}-{end - 1}/{size}"}, timeout=600)
            r.raise_for_status()
            start = end
    status = "PROCESSING"
    for _ in range(30):
        s = requests.post(f"{API}/v2/post/publish/status/fetch/", json={"publish_id": publish_id}, headers=h, timeout=30)
        status = s.json().get("data", {}).get("status", "UNKNOWN")
        if status in ("PUBLISH_COMPLETE", "FAILED"):
            break
        time.sleep(10)
    return publish_id, status, new_refresh
