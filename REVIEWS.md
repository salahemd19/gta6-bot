# Texts for the platform reviews (accurate descriptions of what the tool really does)

## YouTube: OAuth verification and API Services audit
**What the app does:** A personal automation for one YouTube channel ("VICECITY INTEL"). It uploads short vertical
videos (YouTube Shorts) that the channel owner created, using `videos.insert`, and reads the view/like counts of the
owner's own videos (`videos.list`, `channels.list`) to measure performance.
**Scopes:** `https://www.googleapis.com/auth/youtube.upload` (publish the owner's videos) and
`https://www.googleapis.com/auth/youtube.readonly` (read the owner's own channel statistics).
**Users:** one (the channel owner). No third-party users, no data about viewers or subscribers is collected,
stored or shared. Tokens are kept in encrypted repository secrets and can be revoked in Google Account security.
**Quota usage:** at most 4 uploads per day (about 6,400 units/day of the default 10,000 allocation).
**Compliance:** The app follows the YouTube API Services Terms of Service and Developer Policies; privacy policy and
terms are published at the Pages URLs.

## TikTok: app description (Content Posting API)
**App name:** GTA Clipper / VICECITY INTEL Poster
**Description:** A personal tool that publishes short fan-made GTA VI montages to the owner's own TikTok account.
**Use case for Content Posting API:** The owner authorises the app once (Login Kit). The app then uploads finished
videos with `video.publish` (Direct Post) on a fixed schedule to that same account. No other users.
**Compliance:** Posts follow TikTok's Community Guidelines and the Content Sharing Guidelines: user-authorised
account, accurate captions, AIGC/commercial disclosures where applicable, no mass posting (cap: 8 posts/day).

## TikTok: demo video script (about 1 minute, screen recording)
1. Show the home page, terms and privacy pages on github.io.
2. Run `python tools/tiktok_auth.py`; show the TikTok consent screen listing `video.publish` and `video.upload`;
   approve; show the terminal printing "authorised".
3. Show a finished 9:16 video in the queue folder; run the post step; show the video appearing in TikTok Studio on
   the owner's account.
4. Show how to revoke access (TikTok > Settings > Security > Manage app permissions).
