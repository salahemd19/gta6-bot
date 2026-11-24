"""YouTube upload through the official Data API v3 using a stored refresh token (no browser, no laptop).

Env: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
Note: until Google's API Services audit approves the project, videos uploaded through the API are locked private.
"""
import os
import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


def access_token():
    r = requests.post(TOKEN_URL, data={
        "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def upload(path, title, description, privacy="public"):
    """Resumable upload; returns the new video id."""
    token = access_token()
    meta = {"snippet": {"title": title[:100], "description": description, "categoryId": "20"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
    size = os.path.getsize(path)
    init = requests.post(UPLOAD_URL + "?uploadType=resumable&part=snippet,status", json=meta, headers={
        "Authorization": f"Bearer {token}", "X-Upload-Content-Length": str(size),
        "X-Upload-Content-Type": "video/mp4"}, timeout=60)
    init.raise_for_status()
    with open(path, "rb") as f:
        up = requests.put(init.headers["Location"], data=f, headers={"Content-Type": "video/mp4"}, timeout=600)
    up.raise_for_status()
    return up.json()["id"]
