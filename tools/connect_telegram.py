"""Run this yourself, once: connect your Telegram bot to the pipeline.

 1. In Telegram, open @BotFather, send /newbot, choose a name. BotFather replies with a token.
 2. Copy that token (just copy it, do not paste it anywhere).
 3. Run:  python tools/connect_telegram.py
 4. Send the 6-digit code this script shows to your new bot.

The token is read from the clipboard, stored as a GitHub secret and cleared from the clipboard. It is never printed.
"""
import json
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from renew_youtube_secrets import REPO, github_signed_in  # noqa: E402

TOKEN_SHAPE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")


def clipboard():
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"], capture_output=True, text=True)
    return r.stdout or ""


def clear_clipboard():
    subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value ' '"], capture_output=True)


def api(token, method, **data):
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}",
                                    urllib.parse.urlencode(data).encode(), timeout=60) as r:
            return json.load(r)["result"]
    except urllib.error.HTTPError as e:
        sys.exit(f"Telegram refused the request ({e.code}). Copy the token again from @BotFather and rerun.")
    except urllib.error.URLError:
        sys.exit("Cannot reach Telegram. Check the internet connection and rerun.")


def wait_for_code(token, code, seconds=180):
    end, offset = time.time() + seconds, 0
    while time.time() < end:
        for u in api(token, "getUpdates", timeout=20, offset=offset):
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            chat = msg.get("chat") or {}
            if chat.get("type") == "private" and str(msg.get("text", "")).strip().endswith(code):
                api(token, "getUpdates", offset=offset, limit=1)
                return chat
    sys.exit("The code did not arrive within 3 minutes. Rerun the script.")


def main():
    m = TOKEN_SHAPE.search(clipboard())
    if not m:
        sys.exit("No bot token on the clipboard. In Telegram, copy the token @BotFather gave you, then rerun.")
    token = m.group()
    bot = api(token, "getMe")
    if not github_signed_in():
        sys.exit("GitHub is not signed in here. In this window run: gh auth login   (then run this again)")
    code = f"{secrets.randbelow(900000) + 100000}"
    print(f"Open https://t.me/{bot['username']} in Telegram, press Start, then send this code to the bot:  {code}")
    chat = wait_for_code(token, code)
    for name, value in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", str(chat["id"]))):
        r = subprocess.run(["gh", "secret", "set", name, "--repo", REPO], input=value, text=True, capture_output=True)
        if r.returncode:
            sys.exit(f"Could not save {name}: {r.stderr.strip()[-200:]}")
        print("saved", name)
    clear_clipboard()
    api(token, "sendMessage", chat_id=chat["id"],
        text="✅ Connecté. Les vidéos à valider arrivent ici avec les boutons Publier / Rejeter. Réponses prises en compte "
             "en quelques minutes. Commandes : /statut /pause /reprendre /aide")
    subprocess.run(["gh", "workflow", "run", "telegram.yml", "--repo", REPO], capture_output=True)
    print(f"Done. Connected to {chat.get('first_name', 'your chat')}. The waiting videos will arrive in a few minutes.")


if __name__ == "__main__":
    main()
