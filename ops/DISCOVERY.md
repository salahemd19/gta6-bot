# VICECITY INTEL — discovery radar (Phase 2, 26 Nov 2026)

`cloud/radar.py` runs hourly (`.github/workflows/radar.yml`). It finds and organises candidates. It downloads no video and publishes nothing. Settings (keywords, feeds, channels, limits) are in `config/radar.json`.

## Sources

| Source | Status | What it gives | Limits |
|---|---|---|---|
| Kick viewer clips | Working, tested | New and most-viewed GTA 6 clips, creator, URL, views, growth between scans | Public web endpoint, not part of the documented API. Kick can block it |
| Kick live streams (official API) | Working, tested | Top live GTA 6 streams, language, viewers | 25 streams per scan |
| Kick chat spikes | **Blocked at the last local test** (HTTP 429, security policy). It worked on some streams in the first run | Live moments where chat spiked | One probe per stream; the radar stops when refused and does not work around it |
| Google News RSS (FR, EN) | Working, tested | Articles, secrets news | Headlines and links only; Google intends the feeds for personal, non-commercial reading |
| jeuxvideo.com RSS | Working, tested | French GTA articles | Headlines and links only |
| Google Trends RSS (France) | Working, tested | GTA terms when they trend (often none) | Daily trending searches only |
| YouTube channel feeds | Working, tested | New uploads of monitored channels | Only Rockstar Games is listed. Add verified channel IDs in the config |
| Twitch | Code written, **not connected, not tested** | Top clips of the last 24 h | Secrets `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` (free developer app) |
| YouTube search and live | Code written, **not connected, not tested** | Videos and live streams by keyword | Secret `YT_API_KEY`. Runs every 6 h for quota reasons |
| Reddit (r/GTA6, r/GTAVI, r/GTA) | Code written, **not connected, not tested** | Top posts of the day | Secrets `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`; anonymous access is refused |
| TikTok, Instagram, X, Facebook Gaming, Discord | **Unavailable** | Nothing automated | No usable official API (X is paid, Discord needs server admins). Manual watch only. No scraping |

## Data

| File | Content |
|---|---|
| `db/clips.json` | Clip candidates: source, creator, URL, dates, views, radar priority, topics, analysis scores, status, rights |
| `db/creators.json` | Creator database: platform, language, clips, views, peak viewers, best score, used/rejected, original or likely repost |
| `db/items.json` | Live streams, live moments, videos, articles (kept 7 days) |
| `db/topics.json` | Per topic: creator content and news in the last 24 h, previous 24 h, trend, examples |
| `db/radar_log.json` | One entry per run with each source's state (last 240) |
| `ops/radar_dashboard.html` | Searchable dashboard, published as a private page: https://claude.ai/artifact/PkkRoQR74E6uThjRzg4mEb (the laptop task republishes it) |

## Priority

Radar priority (0–10), from metadata only: momentum 40 %, topic match 15 %, originality 15 %, French signal 10 %, freshness 10 %, usable length 10 %. The engine analyses the highest priority first, then scores visual impact, emotional impact, entertainment, share potential, replayability and French relevance from the video.

Known weaknesses: clip titles are often meaningless, so topic matching and French detection are weak; repost detection looks only at the account name; storytelling is not measured; real originality and GTA 6 authenticity need a human or a vision model.

## Duplicates

Clips by id, articles by link, videos by video id, plus a frame hash during analysis. Clips already published are listed in `db/used_scenes.json`.
