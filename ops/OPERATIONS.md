# VICECITY INTEL — operations (Phases 5 to 8, 27 Nov 2026)

## Flow
radar (hourly) → engine: ingest and analysis (3 h) → **footage review** → factory (production) → **owner approval** (GitHub issue) → calendar → posting → analytics → reports. `operations` (hourly, and on every approval) supervises it all.

| Part | File | Runs |
|---|---|---|
| Factory | `cloud/factory.py`, `config/templates.json` | `operations` job `produce`, or by hand |
| Narration test render | `.github/workflows/factory.yml` | by hand |
| Calendar and publishing records | `cloud/publisher.py`, `config/publishing.json`, `queue/calendar.json` | every `operations` run |
| Analytics and reports | `cloud/analytics.py`, `db/metrics.jsonl`, `ops/reports/` | hourly / twice a day |
| Orchestrator and control centre | `cloud/ops.py`, `ops/control_center.html` | hourly |

## Production rules
Exported only if: reviewed and kept (`db/reviews.json`), publishable rights, authenticity verified, footage never used. At least 3 clips from 3 different creators. A quality-check failure blocks submission. The YouTube export must contain a licensed music file (`music/files/<track id>.mp3`, not in the repository); TikTok sound is added in TikTok's own picker.

`credited_third_party` counts as publishable by owner decision (26 Nov). It is **not** permission from the creator.

Quality checks: resolution, 9:16, codec and frame rate, duration, audio, decode errors, loudness, true peak, silence, black and frozen frames, subtitle timing and speed, narration present, header branding, source resolution, duplicate footage, music licence and presence, attribution.

## Publishing
Windows (Paris, CET/CEST automatic) differ by platform. Daily caps start at 6 YouTube and 8 TikTok; targets 8 and 12. Raise `level` in `config/publishing.json` when slots are being filled with good videos. Time windows are experiments.
```
python cloud/publisher.py status
python cloud/publisher.py mark <id> youtube posted --url <link>
python cloud/publisher.py hold <id> "reason"      (release <id> to undo)
```
Publishing is blocked for: no approval, unpublishable rights, unresolved authenticity, `factual_issue`, hold, same footage or title. Failed uploads retry 3 times; missed slots are logged and re-assigned. History: `db/publish_history.jsonl`. Errors: `db/publish_errors.jsonl`.

## Analytics
YouTube readings come from the channel's own API token. TikTok and watch-time metrics need an export: `python cloud/analytics.py import file.csv --platform tiktok`. Checkpoints 1 h, 3 h, 24 h, 7 d. Recommendations need 20 videos with a 24 h reading and 5 per group; medians only; correlations, not causes. Score weights are not changed automatically. Not built: automatic discovery of new creators or topics from results, hook rewriting, pacing changes.

## Manual control
```
python cloud/ops.py pause            stop everything, including cloud posting (commit and push config/overrides.json)
python cloud/ops.py resume
python cloud/ops.py disable produce
python cloud/ops.py run --job calendar
```

## Recovery
- Failed or stale workflow: restarted once automatically, then listed in the `ops-alert` issue.
- Damaged database: `python cloud/contentdb.py restore <backup.zip> --into <folder>`; backups are in the release `backups`.
- Bad state file: delete `db/ops_state.json`; it is rebuilt.

## Tested on 27 Nov
- Factory: local top 3 with music, and a cloud top 3 with French narration (test renders, not published). Both pass with warnings (music or attribution).
- Calendar, gates, retries, CET/CEST, analytics checkpoints, factory gate: unit tests.
- Cloud runs: `operations`, `factory-test`, `backup` succeeded.
- **Not working: YouTube analytics and API posting in the cloud.** The stored refresh token is refused (401).
- Not yet exercised for real: factory submission to an approval issue, a calendar-assigned post, automatic recovery, the alert issue.

## Remaining manual work
0. **Renew the YouTube authorisation** and update the secret `YT_REFRESH_TOKEN` (until then, readings come from the laptop log).
1. **Watching footage** and writing the keep/reject review. The automatic score cannot do it.
2. **Approving** each video (label `approved`).
3. **Posting**: the laptop task posts through the browser until the YouTube API audit and TikTok app review pass; then set the repository variable `CLOUD_PLATFORMS`.
4. **Music files**: only one licensed track is on the laptop. Download more from YouTube Audio Library and check each attribution flag. The cloud has none, so cloud production waits.
5. **French narration** works only where Piper is installed (cloud test workflow). Not installed on the laptop.
6. **TikTok analytics** export and import.
7. Speech in other languages is not translated into French subtitles.
8. The control centre page in Claude is a snapshot; it updates when republished.
