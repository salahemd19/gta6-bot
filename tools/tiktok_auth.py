"""One-time TikTok authorisation: prints the refresh token to store as the TIKTOK_REFRESH_TOKEN secret.

  python tools/tiktok_auth.py <client_key> <client_secret> <pages_base_url>
e.g. python tools/tiktok_auth.py abc123 s3cret https://vicecityintel.github.io/gta6-bot

The redirect URI registered in the TikTok app must be <pages_base_url>/callback.html, a page that just shows the
?code= value so you can copy it back here.
"""
import secrets
import sys
import urllib.parse
import webbrowser

import requests

key, secret, base = sys.argv[1], sys.argv[2], sys.argv[3].rstrip("/")
redirect = base + "/callback.html"
state = secrets.token_urlsafe(12)
url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
    "client_key": key, "scope": "user.info.basic,video.publish,video.upload", "response_type": "code",
    "redirect_uri": redirect, "state": state})
print("Opening the TikTok consent page. Approve, then copy the code shown on the callback page.")
webbrowser.open(url)
code = input("Paste the code: ").strip()
r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", data={
    "client_key": key, "client_secret": secret, "code": code, "grant_type": "authorization_code",
    "redirect_uri": redirect}, timeout=30)
r.raise_for_status()
d = r.json()
print("authorised for open_id", d.get("open_id"))
print("TIKTOK_REFRESH_TOKEN =", d["refresh_token"])
