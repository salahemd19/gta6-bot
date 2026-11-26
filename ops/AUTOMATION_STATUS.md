# VICECITY INTEL — automation status and roadmap (26 Nov 2026)

## Architecture (one system, no extra subscriptions)

```
Kick API ──► cloud/engine.py (GitHub Actions, every 3 h, free)
              DISCOVER → DEDUPE → ANALYSE → SCORE → SELECT → PRODUCE → PACKAGE
                   │                                              │
                   ▼                                              ▼
            db/clips.json  ◄──── feedback ──── GitHub issue (REVIEW, owner approves on phone)
          (central database)                                      │
                                                                  ▼
                                    queue/manifest.json ──► bot/post_next.py (cloud, rights gate, Paris windows)
                                                       └──► laptop task (Chrome Studios) until the APIs are approved
                                                                  │
                                                         MEASURE → stats → scoring weights (to build)
```

Storage: GitHub repo (database and queue as JSON), GitHub Release assets (videos and frame sheets), GitHub Issues (review).
Compute: GitHub Actions (free). Music: `music/` library and recommender. Brand sounds: `music/sfx`.

## Component status

| Component | Status | Evidence / limitation |
|---|---|---|
| Kick discovery (viewer clips, day/week, paging, retries) | **WORKING AND TESTED** | 26 Nov local run: 107 clips into db/clips.json |
| Central database (source, creator, URLs, timestamps, metrics, scores, pillar, authenticity, rights, duplicates, status, usage) | **WORKING AND TESTED** | db/clips.json |
| Duplicate detection (clip id + perceptual frame hash) | **IMPLEMENTED BUT NOT FULLY TESTED** | Runs on every analysed clip; no duplicate observed yet |
| Analysis: motion, frozen frames, cutscene letterbox, audio peaks, best 6.5 s window | **WORKING AND TESTED** | 15 of 30 auto-rejected in the test |
| Scoring (visual, emotional, entertainment, share velocity, replayability, French relevance) | **WORKING AND TESTED, but weak** | Measurable signals only. In the test it still picked an IRL clip and a cutscene. Storytelling, originality and "is it really GTA 6" are not judged |
| AI vision scoring and authenticity (GTA 6 vs GTA V / IRL / cutscene) | **REQUIRES A NEW SERVICE** | Needs an Anthropic API key as a GitHub secret (about a few cents per clip). Until then: Claude review by eye (laptop task) plus owner approval |
| Pillar classification | **IMPLEMENTED BUT NOT FULLY TESTED** | Keyword-based on the clip title; mostly falls back to VIRAL MOMENTS |
| Production: top 3 montage, French title, countdown, credits, 9:16, brand sounds, upload-size export, frame sheet | **WORKING AND TESTED** | 13 videos on 26 Nov |
| French hooks, titles, descriptions, hashtags | **WORKING AND TESTED** | Template-based, rotated per run |
| French narration / voice-over, subtitles | **NOT BUILT YET** | Narration needs a TTS service (REQUIRES A NEW SERVICE) |
| Pillar templates (6 looks) | **NOT BUILT YET** | One generic template today |
| Music recommendation per video | **WORKING AND TESTED** | Added to the package and the issue; applying it is manual (Studio editor or TikTok picker) |
| Review: issue with frame sheet, sources, music, authenticity checklist | **IMPLEMENTED BUT NOT FULLY TESTED** | First cloud run in progress |
| Feedback: owner decisions → database | **IMPLEMENTED BUT NOT FULLY TESTED** | Needs a first approve/reject |
| Rights gate | **WORKING AND TESTED** | Owner policy: credited third-party publishable, refused never |
| Cloud publishing YouTube | **REQUIRES MANUAL ACTION** | Google API audit pending (uploads forced private until then) |
| Cloud publishing TikTok | **REQUIRES MANUAL ACTION** | TikTok app review pending |
| Publishing via Chrome (laptop task) | **WORKING AND TESTED** (manual-assisted) | Needs the laptop on; about 10 min per video per platform |
| TikTok in-app music on the cloud path | **NOT CURRENTLY POSSIBLE** | The API can't add library sounds |
| Analytics YouTube | **AVAILABLE BUT NOT CONNECTED** | Studio stats readable in Chrome; Analytics API needs a new OAuth scope |
| Analytics TikTok | **REQUIRES MANUAL ACTION** | Display API needs the approved app |
| Twitch / YouTube search / Reddit discovery | **REQUIRES A NEW SERVICE** | Free developer keys; creating each needs the owner's OK |
| TikTok / Instagram / X / Facebook discovery | **NOT CURRENTLY POSSIBLE** | No usable official API; no scraping |

## Roadmap (impact → ease → cost → reliability → scale)

1. **Vision scoring and authenticity check with Claude in the engine** (biggest quality jump; needs an API key).
2. **Engine every 3 h + Claude pre-screen + owner approval**: the steady supply of 12+ candidates a day.
3. **YouTube analytics pull** (views, retention, average view duration per video) into the database, with a daily report and scoring weights learned per pillar and per slot.
4. **Cloud publishing** the day Google and TikTok approve (set `CLOUD_PLATFORMS`).
5. **French subtitles** with Whisper, burned in when speech is French.
6. **Pillar templates and recurring series branding.**
7. **More discovery sources** (Twitch, YouTube, Reddit keys).
8. **French narration** (TTS service).
9. **Leonida platform** (map, database, guides), once the media engine runs on its own.
