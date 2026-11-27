"""Run this yourself: copy the YouTube authorisation that already works on this computer to the GitHub secrets.

  python tools/renew_youtube_secrets.py

It checks that Google still accepts it, stores three secrets in your repository and starts a test run.
Nothing secret is printed or written to any file.
"""
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "salahemd19/gta6-bot"
TOKEN = Path(__file__).resolve().parents[2] / "yt_token.json"


def main():
    if not TOKEN.exists():
        sys.exit("No saved authorisation found. In the project folder run: python youtube_upload.py auth")
    d = json.loads(TOKEN.read_text(encoding="utf-8"))
    values = {"YT_CLIENT_ID": d.get("client_id"), "YT_CLIENT_SECRET": d.get("client_secret"),
              "YT_REFRESH_TOKEN": d.get("refresh_token")}
    if not all(values.values()):
        sys.exit("The saved authorisation is incomplete. In the project folder run: python youtube_upload.py auth")
    form = urllib.parse.urlencode({"client_id": values["YT_CLIENT_ID"], "client_secret": values["YT_CLIENT_SECRET"],
                                   "refresh_token": values["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"}).encode()
    try:
        urllib.request.urlopen("https://oauth2.googleapis.com/token", form, timeout=30)
    except urllib.error.HTTPError as e:
        sys.exit(f"Google refused it ({e.code}). In the project folder run: python youtube_upload.py auth, then run this again.")
    if subprocess.run(["gh", "auth", "status"], capture_output=True).returncode:
        sys.exit("GitHub is not signed in here. Run this from the Terminal panel inside the Claude app.")
    for name, value in values.items():
        r = subprocess.run(["gh", "secret", "set", name, "--repo", REPO], input=value, text=True, capture_output=True)
        if r.returncode:
            sys.exit(f"Could not save {name}: {r.stderr.strip()[-200:]}")
        print("saved", name)
    subprocess.run(["gh", "workflow", "run", "ops.yml", "--repo", REPO, "-f", "job=analytics_collect"], capture_output=True)
    print("Done. A test run has started.")


if __name__ == "__main__":
    main()
