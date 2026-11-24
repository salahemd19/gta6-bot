# Setup checklist (all free). Steps marked YOU need your hands (accounts, approvals, codes).

## A. GitHub (YOU, 10 min)
1. Create a free GitHub account (github.com/signup) with salahemd19@gmail.com. Pick a username, e.g. `vicecityintel`.
2. Create a new **public** repository named `gta6-bot` (public = unlimited free Actions minutes; secrets stay private).
3. Upload this whole folder (drag and drop in the web UI, or `git push`). Keep the `.github`, `bot`, `docs`, `queue` folders.
4. Settings > Pages > Source: "Deploy from a branch", branch `main`, folder `/docs`. Your site is then
   `https://<username>.github.io/gta6-bot/` (home, terms.html, privacy.html, callback.html).

## B. YouTube: remove the private-only lock (YOU, forms; free)
1. Google Cloud console > project `gta-clipper` > Google Auth Platform > Branding: app name, user support email,
   **Application home page** = your Pages URL, **Privacy policy** = privacy.html URL, **Terms** = terms.html URL,
   authorised domain `github.io`. Then **Publish app** (move from Testing to In production) and submit
   verification for the `youtube.upload` scope. Texts to paste are in REVIEWS.md.
2. Submit the **YouTube API Services compliance audit** form (link in YouTube API docs, "Compliance Audits").
   Until it is approved, API uploads stay private.
3. Refresh token: `python tools/yt_refresh_token.py` prints the token to store as a secret (I can do this for you
   from the project folder; the token is already in `yt_token.json`).

## C. TikTok (YOU, forms; free)
1. developers.tiktok.com > your app `GTA Clipper` > fill: icon (1024x1024), description, category, Terms URL,
   Privacy URL, Web URL (Pages site), add products **Login Kit** and **Content Posting API**, redirect URI
   `https://<username>.github.io/gta6-bot/callback.html`, scopes `video.publish` and `video.upload`.
2. Record the demo video (script in REVIEWS.md), submit for review. Enable "Direct Post" in the app.
3. When approved: `python tools/tiktok_auth.py` (opens the consent page, you approve once, prints the refresh token).

## D. Secrets (YOU paste, or I add them through your signed-in browser)
Repository > Settings > Secrets and variables > Actions > New repository secret:
`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`, `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`.
Values are in the local `.env` / `yt_token.json`; never paste them in chat.

## E. Start
Actions tab > "post-next" > Run workflow (test). From then on it runs every 2 hours by itself, laptop off.
Videos for the queue are hosted as GitHub Release assets (`video_url` in `queue/manifest.json`).
