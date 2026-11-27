"""Run this yourself, once: connect your Buffer account to the pipeline.

 1. In Buffer, connect the YouTube and TikTok channels, then create an API key (publish.buffer.com/settings/api).
 2. Copy the key.
 3. Run:  python tools/connect_buffer.py

The key is read from the clipboard, checked with Buffer, stored as a GitHub secret and cleared from the clipboard.
It is never printed. Posting does not start yet: that needs "poster": "buffer" in config/publishing.json.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cloud")]
import buffer_post  # noqa: E402
from connect_telegram import clear_clipboard, clipboard  # noqa: E402
from renew_youtube_secrets import REPO, github_signed_in  # noqa: E402


def main():
    key = clipboard().strip()
    if len(key) < 20 or any(c.isspace() for c in key):
        sys.exit("No API key on the clipboard. Copy the key in Buffer (not this command), then rerun.")
    os.environ["BUFFER_API_KEY"] = key
    try:
        found = buffer_post.channels()
    except Exception as e:  # noqa: BLE001 - the message never contains the key
        sys.exit(f"Buffer did not accept it: {type(e).__name__}: {str(e)[:150]}")
    if not github_signed_in():
        sys.exit("GitHub is not signed in here. In this window run: gh auth login   (then run this again)")
    r = subprocess.run(["gh", "secret", "set", "BUFFER_API_KEY", "--repo", REPO], input=key, text=True, capture_output=True)
    if r.returncode:
        sys.exit(f"Could not save the secret: {r.stderr.strip()[-200:]}")
    clear_clipboard()
    print("saved BUFFER_API_KEY")
    print("Channels Buffer can post to:", ", ".join(sorted(found)) or "none")
    missing = [p for p in ("youtube", "tiktok") if p not in found]
    if missing:
        print("Still to connect in Buffer:", ", ".join(missing))
    subprocess.run(["gh", "workflow", "run", "ops.yml", "--repo", REPO, "-f", "job=post_buffer"], capture_output=True)
    print("Done. Tell Claude, so posting can be switched on.")


if __name__ == "__main__":
    main()
