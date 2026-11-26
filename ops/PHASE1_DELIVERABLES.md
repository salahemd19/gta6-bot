# VICECITY INTEL — Phase 1 deliverables (26 Nov 2026)

## 1. Project audit (what exists, tested 26 Nov)

| Area | Where | Verified |
|---|---|---|
| Kick discovery (viewer clips day/week, paging, retry) | `cloud/engine.py` `discover()` | Yes: 107 clips in local run, 45 in cloud run |
| Central database | `db/clips.json` | Yes: creator, URL, timestamps, metrics, score, pillar, rights, duplicates, status, usage |
| Analysis (motion, frozen frames, cutscene letterbox, audio peak) | `clipper.py`, `engine.py` | Yes: auto-rejects about 60–70 % of candidates |
| Duplicate detection (perceptual hash) | `engine.py` `dhash()` | One duplicate caught in the cloud run |
| Scoring | `engine.py` `score()` | Measurable signals only; not yet reliable (one IRL clip and one cutscene got through the first test) |
| Production (top 3 / top 5, French title, credits, brand sounds, 9:16) | `cloud/montage.py`, `engine.py` `produce()` | Yes: 13 videos on 26 Nov; cloud run produced `engine-20261126-1925-1` |
| Review (GitHub issue with frame sheet, music, authenticity checklist) | `bot/approvals.py`, `engine.py` `publish_package()` | Issue #7 open for review |
| Owner feedback → database | `engine.py` `feedback()` | Implemented; not yet exercised with a real approve/reject |
| Music library and recommender | `music/` | Yes: 21 tracks with per-platform licence status; usage log |
| Publishing: YouTube and TikTok | `bot/post_next.py` (cloud), Chrome Studios (manual-assisted) | Cloud blocked by API approvals; Chrome path used for all 26 Nov posts |
| Rights gate | `bot/post_next.py` `rights_ok()` | Yes; owner policy: `credited_third_party` publishable, `refused` never |
| Paris posting windows (CET/CEST via zoneinfo) | `bot/post_next.py` `HOT` | Yes (tested) |

## 2. Brand strategy (final for Phase 1)

- **Name and promise:** VICECITY INTEL — the French-first GTA 6 discovery and information brand. Tagline: *« Le renseignement GTA 6. »*
- **Audience:** French-speaking GTA 6 fans, mainly in France; secondary Belgium, Switzerland, Québec.
- **Language:** French for hooks, titles, captions and narration. Original English or Spanish speech is kept as game audio, never presented as ours.
- **Identity:** dark charcoal (#121218), cyan (#00E5FF), magenta (#FF2BD6); Anton display type; the signature 4-sound pack (intro, transition, reveal, outro) in every video.
- **Differentiation:** fast, curated *top 3 / top 5 moments* built from real GTA 6 gameplay on Kick, with French countdown hooks and creator credit. Not reposts of single clips, and never GTA V passed off as GTA 6.
- **Six pillars** (as in the master plan): Map & secret discoveries · Racing & vehicles · Viral moments & chaos · Cheats, tips & money · Challenges & experiments · Leonida life & details. Today only *Viral moments & chaos* is produced at volume; the other five need their own discovery queries and templates (Phase 2/5).
- **Authenticity rule:** only real GTA 6 gameplay; no invented cheats, stats or secrets; anything unclear goes to human review.

## 3. Measurable objectives (baseline 26 Nov → 30 days)

| Metric | Baseline (26 Nov) | 30-day target |
|---|---|---|
| Videos published / day (YouTube + TikTok) | 14 (manual, one day) | 8 YT + 12 TT on average, via automation once approved |
| Share of automatically produced videos that pass review | not measured | ≥ 70 % |
| Share of videos with rights `credited_third_party` or better | 100 % (third-party) | 100 % with credit on screen |
| Average view duration / retention | not measured (Studio manual) | Tracked daily from YouTube Analytics and TikTok |
| Followers | not recorded | Tracked weekly |
| Owner minutes per day | ~45 min | ≤ 10 min (approvals only) |

## 4. Technical architecture (single source of truth)

- **Data:** `db/clips.json` (content database), `queue/manifest.json` (publish queue), `music/library.json` (music), `music/usage_log.json` (music history).
- **Compute:** GitHub Actions (free): `engine.yml` every 3 h; `post.yml` every 30 min; `make-clips.yml` disabled.
- **Storage:** GitHub Releases (video and sheet assets); GitHub Issues (review).
- **Config:** repo variables (`CLOUD_PLATFORMS`) and secrets (Kick, YouTube, TikTok). Hot windows and targets live in `bot/post_next.py`.
- **Laptop:** Claude scheduled task `gta6-daily-posting` (Chrome Studios) until the APIs are approved.

## 5. Existing capability inventory → what to keep

Keep: `cloud/kick_api.py`, `cloud/chat_signal.py`, `cloud/clipper.py` (visual and audio checks), `cloud/montage.py`, `cloud/engine.py`, `bot/approvals.py`, `bot/post_next.py`, `bot/yt.py`, `bot/tiktok.py`, `music/*`.

Retire (superseded, duplicated): `cloud/make_clips.py` (live-capture pipeline, weak picks) and `.github/workflows/make-clips.yml` (disabled). `shots_used.json`, `trailer_montage.py` and `approval_page.html` (old Claude page) belong to the trailer era and can be archived.

Duplicated: two montage scripts in `cloud/` (`montage.py` and the one inside `make_clips.py`). Keep `montage.py`.

## 6. Missing functionality (prioritised)

1. **Vision scoring and authenticity** (Claude API key as a secret; the biggest quality gap) — *requires a new service*.
2. **Analytics pull** (YouTube Analytics: views, retention, average view duration per video → database) — *needs a new OAuth scope*.
3. **Cloud publishing** — *blocked by Google audit and TikTok review (manual)*.
4. **Pillar templates and voice-over / subtitles** — *needs TTS / Whisper*.
5. **Discovery beyond Kick** — *needs Twitch, YouTube and Reddit developer keys (owner OK)*.
6. **Owner-feedback loop test** — *needs one real approve or reject on issue #7*.

## 7. Prioritised roadmap (impact → ease → cost → reliability → scale)

| # | Item | Depends on | Owner action |
|---|---|---|---|
| 1 | Approve or reject issue #7 (tests the feedback loop) | — | yes |
| 2 | Claude vision pre-screen in the engine (authenticity, GTA 6 vs V/IRL) | API key secret | create key |
| 3 | YouTube Analytics pull → database → per-pillar and per-slot report | new OAuth scope | re-authorise |
| 4 | Enable cloud publishing (`CLOUD_PLATFORMS`) | Google audit, TikTok review | wait for replies |
| 5 | Pillar templates for the other five pillars and their discovery queries | — | none |
| 6 | Subtitles (Whisper) and French narration (TTS) | service choice | decide |
| 7 | Twitch / YouTube / Reddit discovery | developer keys | approve |
| 8 | Leonida platform (map, database, guides) | 1–7 running | later |

## 8. Known issues

- The engine's score is not reliable yet; review by eye is still needed for every video.
- Music is recommended but applied by hand in the Studio editor or TikTok's picker.
- Cloud posting and analytics pull wait on external approvals.
