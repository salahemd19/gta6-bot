"""Print the YouTube refresh token stored in yt_token.json (run locally; paste it into the YT_REFRESH_TOKEN secret).
Do not share the output. If the Google app is still in 'Testing' mode the token expires after 7 days: publish the
app (see SETUP.md, section B) and re-run `python youtube_upload.py auth` to get a long-lived token."""
import json
import sys

p = sys.argv[1] if len(sys.argv) > 1 else "yt_token.json"
print("YT_REFRESH_TOKEN =", json.load(open(p))["refresh_token"])
