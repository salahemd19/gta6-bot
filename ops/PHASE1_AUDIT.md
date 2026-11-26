# VICECITY INTEL — Phase 1: audit and strategic foundation (26 Nov 2026)

## 1. What exists and works (tested)

| Area | Component | Status |
|---|---|---|
| Channels | YouTube "VICECITY INTEL" (salahemd19), TikTok @vicecity_intel1 | Live. 26 Nov: 8 TikTok + 6 YouTube posted or scheduled, all through the Studio web UIs in Chrome |
| Discovery | Kick official API (client credentials) + public Kick clips endpoint `api/v2/categories/grand-theft-auto-vi/clips` | Works. ~160 clips per scan, sorted by views/day/week |
| Discovery | Kick chat history (`api/v2/channels/{id}/messages`) | Works; used as a hype signal |
| Scoring | `cloud/clipper.py visual()` (motion, frozen frames, cutscene letterbox) + audio peaks + chat boost | Works, but only as a pre-filter: the final "is this wow?" judgement still needs a human or Claude to look |
| Production | `cloud/montage.py`: countdown top 3 / top 5, French title, rank, creator credit, 9:16, brand sounds | Works; 13 videos produced 26 Nov |
| Music | `music/library.json` (21 tracks, licence status per platform), `recommend.py`, usage log | Works. YouTube Audio Library tracks are approved for YouTube; commercial hits are TikTok in-app only |
| Sound identity | `music/sfx` intro / transition / reveal / outro (original, owned) | Works, mixed into every montage |
| Approval | GitHub Issues (`a-valider` / `approved` / `rejected`) + `bot/approvals.py` | Works (tested); not yet used for the new top-N format |
| Publishing (cloud) | `post.yml` every 30 min → `bot/post_next.py` | Runs, but posts nothing until `CLOUD_PLATFORMS` is set, which needs the API approvals below |
| Publishing (laptop) | Claude scheduled task `gta6-daily-posting` (every 2 h) | Works only while the laptop is on |
| Cloud clip maker | `make-clips.yml` (live capture) | **Paused**: live-capture picks were weak; to be switched to the Kick-clips source |

## 2. External approvals (blocking full automation)

| Item | Status | Effect |
|---|---|---|
| YouTube Data API audit (project gta-clipper 830132477061) | Submitted 25 Nov; no reply yet | API uploads are forced private until approved |
| TikTok production app "VICECITY INTEL Poster" (Login Kit + Direct Post) | In review since 26 Nov | API cannot post publicly until approved |

## 3. Discovery sources (verified 26 Nov, not assumed)

| Source | Access today | What is needed |
|---|---|---|
| Kick | ✅ API + clips + chat | — |
| Twitch | ❌ Helix needs an app token (401) | Free Twitch developer app (account action: owner's approval) |
| YouTube / YouTube Live | ❌ our OAuth token is upload-only | A YouTube Data API key on project gta-clipper (owner's approval) |
| Reddit | ❌ anonymous JSON/RSS blocked (403/429) | Free Reddit API app (owner's approval) |
| TikTok, Instagram, X, Facebook Gaming | ❌ no official discovery API we qualify for | Manual watch lists only; no scraping, no bypassing protections |

## 4. Rights and authenticity (new directive)

* Every queue entry now carries `rights`: `owned` / `licensed` / `permission_granted` / `unverified` / `unresolved` / `refused`.
* **Publish gate** (`bot/post_next.py`, and the laptop task): only `owned`, `licensed` and `permission_granted` can be published. Tested: today the queue has **0 publishable items**. Everything we have published so far is third-party footage (Kick streams and viewer clips, Rockstar trailers) with no recorded licence.
* Discovery, scoring and production continue regardless of rights status; only publishing is gated.
* GTA V / FiveM roleplay often appears in Kick's GTA 6 category. It is rejected at review and never labelled GTA 6.

## 5. Changes made in Phase 1

* Daily targets set to **8 YouTube / 12 TikTok**, capped on a rolling 24 h window.
* Paris windows (CET/CEST handled by zoneinfo): lunch 11:30–13:30, afternoon 14:30–15:45, TikTok priority 16:00–18:00, evening 18:00–22:30. These are hypotheses to be re-ranked from analytics.
* Rights field and publish gate added in the cloud poster and the laptop task.

## 6. Gaps by phase

| Phase | Missing |
|---|---|
| 2 Discovery | Twitch / YouTube / Reddit connectors (need the keys in section 3); a scheduled Kick-clips scanner in the cloud |
| 3 Intelligence DB | One database of clips: source, creator, pillar, score, rights, status, usage. Today it is split across JSON files and GitHub issues |
| 4 Scoring | Pillar classification; a Claude vision pass on contact sheets (needs an API key and a budget, or stays manual) |
| 5 Production | French narration/voice-over, subtitles, per-pillar templates, series branding |
| 6 Publishing | Automatic cloud posting (blocked by API approvals); rights-cleared supply |
| 7 Analytics | Daily pull of YouTube Analytics / TikTok stats into the database; per-pillar, per-slot reports |
| 8 Automation | Cloud scanner + producer + reporter on GitHub Actions |
| 9 Platform | Not started (Leonida map, database, guides) |

## 7. Decision needed from the owner

**Rights-cleared supply.** Under the new rule, nothing in the current pipeline is publishable. Options:
1. **Creator permission at scale (recommended):** a standard French/English DM/email template and a permissions log; creators who say yes get `permission_granted` and can be clipped continuously. Discovery and production don't wait for it.
2. **Owned gameplay:** capture GTA 6 ourselves (the owner doesn't own the game today).
3. **Licensed footage:** partnerships or paid licences.
4. **Keep posting third-party clips** with credit and takedown on request. This contradicts the new directive, so it needs the owner's explicit decision.
