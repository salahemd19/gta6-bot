"""Kick official public API helper: app token + GTA VI live stream discovery."""
import json, sys, urllib.parse, urllib.request
from pathlib import Path

API = "https://api.kick.com/public/v1"


def load_env(path=".env"):
    env = {}
    for line in Path(path).read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def _req(url, data=None, headers=None):
    headers = {"User-Agent": "GTAClipperBot/1.0", "Accept": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} on {url.split('?')[0]}: {e.read()[:300].decode(errors='replace')}")


def get_token(env):
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": env["KICK_CLIENT_ID"],
        "client_secret": env["KICK_CLIENT_SECRET"],
    }).encode()
    return _req("https://id.kick.com/oauth/token", body,
                {"Content-Type": "application/x-www-form-urlencoded"})["access_token"]


def api_get(token, path, **params):
    q = urllib.parse.urlencode(params, doseq=True)
    return _req(f"{API}/{path}?{q}", headers={"Authorization": f"Bearer {token}"})


def find_category(token, query="grand theft auto"):
    return api_get(token, "categories", q=query).get("data", [])


def live_streams(token, category_id, limit=20):
    return api_get(token, "livestreams", category_id=category_id, limit=limit,
                   sort="viewer_count").get("data", [])


if __name__ == "__main__":
    tok = get_token(load_env())
    print("token OK")
    for c in find_category(tok):
        print("category:", c.get("id"), c.get("name"))
