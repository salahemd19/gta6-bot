# VICECITY INTEL — content intelligence database (Phase 3, 26 Nov 2026)

## Where it lives
| File | Content |
|---|---|
| `db/clips.json` | One record per candidate (the single source of truth for content) |
| `db/history.jsonl` | Append-only log: time, record, who, each field before and after, note |
| `cloud/contentdb.py` | Data model, lifecycle, gates, search, bulk edits, backup and restore |

## Data model
`content_id`, `creator`, `account_url`, `platform`, `url`, `clip_url`, `created_at`, `discovered_at`, `authenticity` + `authenticity_evidence`, `category`, `subcategory`, `description`, `editorial_notes`, `rights`, `licence`, `rights_basis`, `attribution`, `scores`, `viral_potential`, `radar`, `duplicate_of`, `used_in`, `suggested_hook`, `suggested_title`, `stage`, `state`, `production_status`, `approval`, `publications` (video, platform, status, date), `analytics` (per platform).

## Lifecycle
DISCOVERED → AUTHENTICITY_REVIEW → ANALYSED → SCORED → RIGHTS_RECORDED → EDITORIAL_REVIEW → APPROVED_FOR_PRODUCTION → PRODUCED → APPROVED_FOR_PUBLICATION → SCHEDULED → PUBLISHED → PERFORMANCE_ANALYSED

States: `active`, `rejected`, `duplicated`, `expired` (not analysed within 7 days), `rights_unverified`.

- Manual moves go one step at a time and are refused when a gate fails.
- The pipeline's `sync` moves a record forward only to what its own data shows. It can therefore skip review stages that did not happen in this database (for example clips produced before it existed).
- Production approval needs authenticity `verified_by_review` with evidence. Publication approval also needs publishable rights and attribution.

## Rights
`unverified`, `unresolved` and `refused` can never enter the publication queue.
`credited_third_party` **is publishable** under the owner's 26 Nov decision. It is not verified permission. To require verified rights only, remove it from `PUBLISHABLE` in `contentdb.py` and from `PUBLISHABLE_RIGHTS` in `bot/post_next.py`.

## Use
```
python cloud/contentdb.py stats
python cloud/contentdb.py search --min-score 6 --category RACING --in-state active
python cloud/contentdb.py show VCI-xxxxxxxxxx
python cloud/contentdb.py history VCI-xxxxxxxxxx
python cloud/contentdb.py bulk --creator name --state rejected --note "repost account"      (dry run; add --apply)
python cloud/contentdb.py metrics VCI-xxxxxxxxxx youtube views=1200 likes=40
```
Browser search: the radar dashboard (private page) filters by category, creator, platform, stage, state and score. It is read-only.

## Backups and recovery
Daily `backup.yml`: tests, validation, checksummed zip, test restore, upload to the `backups` release, last 30 kept. Git history is a second copy. Recover with `python cloud/contentdb.py restore file.zip --into folder`, check, then copy over `db/`. A damaged database file stops the tools instead of being overwritten; writes are atomic.

## Access control
Only accounts with write access to the repository (and its own workflows) can change data. **The repository is public, so anyone can read the database, notes and backups.** Do not put private information in notes.

## Limits
- Performance analytics are entered by command; nothing pulls them automatically yet (Phase 7).
- The publishing queue (`queue/manifest.json`) still has its own approval through GitHub issues; the database's approval stages are not yet required by the posting scripts.
- Historic videos are only partly backfilled (clips known from the 26 Nov scans).
- Suggested hooks are category templates, not written from the footage.
- JSON files suit a few thousand records; beyond that move to SQLite.
