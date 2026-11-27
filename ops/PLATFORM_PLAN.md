# VICECITY INTEL — GTA 6 information platform (Phase 9 plan, 27 Nov 2026)

Status: **plan only. Nothing built or bought.** Costs and effort are estimates.

## 1. Strategy
**Product:** the French GTA 6 reference where every claim shows how sure we are and how it was checked.
**Audience:** French-speaking players searching "où trouver", "comment faire", "meilleure voiture".
**Edge:** verification in French, linked to our own videos. Not an edge: map size. Large community maps already exist (State of Leonida, GTADB; one report counts 1,570+ markers in June 2026), so a general interactive map is **not** in the MVP.
**Rule:** build nothing until the demand gate (section 6) passes.

## 2. What we know about demand (weak evidence)
| Signal | Reading | Limit |
|---|---|---|
| Radar, news items in 24 h (26 Nov) | Map and secrets 35, vehicles 12, challenges 5, races 2 | Keyword counts, one day |
| Radar, new clips in 24 h | Funny moments 49, vehicles 5, map and secrets 4 | Supply of clips, not searches |
| Channel history, YouTube total views | Story explainer 1,701; official vehicles 1,023; Vice City history 981 | Mostly pre-launch, not age-adjusted, small |
| Site search demand | **Not measured** | Check Google Trends FR and, once live, Search Console |

Hypothesis to test: vehicles and secrets first. Funny clips drive video views but make poor search pages.

## 3. Prioritisation (1 low – 5 high)
| Feature | Demand | Effort | Error risk | Decision |
|---|---|---|---|---|
| Vehicle database with locations | 4 | 2 | 2 | **MVP** |
| Verified secrets and easter eggs | 4 | 2 | 3 | **MVP** |
| Search, categories, correction log | needed | 1 | 1 | **MVP** |
| Cheat codes (verified only) | 4 | 1 | 4 | MVP if each code is tested |
| Money methods | 4 | 2 | 5 (patches) | Later, with expiry dates |
| Tutorials, mission advice | 3 | 3 | 2 | Later |
| Racing routes | 2 | 2 | 2 | Later |
| Vehicle rankings | 3 | 3 | 4 | Only after a repeatable test method |
| Wildlife and NPCs | 2 | 3 | 3 | Later |
| User submissions | unknown | 3 | 5 | Simple form after launch |
| Interactive map | 4 | 5 | 3 | Deferred; per-entry location images first |
| Community challenges, rankings, accounts | unknown | 5 | 4 | Not planned |

## 4. MVP specification
- **Content:** 30 vehicles, 20 secrets, tested cheat codes. French. Each entry has at least one dated source or our own test.
- **Pages:** home, category list, entry, search, "corrections", "méthode", legal notice, privacy, contact.
- **Entry page:** answer in the first screen, confidence label, game version and date tested, evidence, related video, corrections history.
- **Mobile first:** one column, usable at 360 px, page under 200 KB before images, readable without JavaScript.
- **Search:** static index (Pagefind), accent-insensitive, filters by category and label.
- **SEO:** one URL per entry (`/vehicules/<slug>`, `/secrets/<slug>`), titles written as the question, sitemap, canonical tags, structured data, internal links, updated date.
- **Out of scope:** accounts, comments, map engine, ads, apps, other languages.
- **Done when:** 50 verified entries, search works on a phone, every page passes the schema check, a correction can be published in one commit.

### Confidence labels
| Label | Requirement | Published |
|---|---|---|
| CONFIRMÉ | Official source, or reproduced twice with our own footage | Yes |
| TESTÉ | Reproduced once with footage | Yes |
| SIGNALÉ | One credible community report with video | Yes, clearly marked |
| RUMEUR | No usable evidence | No |
| OBSOLÈTE | Changed by a patch or disproved | Yes, with the correction |

Testing needs someone with the game. We currently have no testing setup: that is the main constraint. Until then only official facts and "SIGNALÉ" are possible.

## 5. Architecture
```
radar + clip database ──> editor review ──> content/*.json (git) ──> static site build ──> hosting
GitHub issue form (submissions, error reports) ──> moderation ──┘          └─> search index, sitemap
```
- **Reuse:** repository, review gate, approval issues, backups, operations workflow.
- **Build:** a small static generator or Astro. No server, no database at first.
- **Hosting:** Cloudflare Pages (free plan: 20,000 files; build allowance 500 a month in one table and 100 in another, check). GitHub Pages has a 100 GB soft monthly bandwidth limit and is not meant for running an online business, so avoid it if the site will earn money.
- **Later:** a database (for example Cloudflare D1: free daily limits of 5 million rows read, 100,000 written) only when submissions or rankings justify it.
- **Backups:** git history plus the existing daily release backup extended to `content/`. Test a rebuild monthly.
- **Moderation:** nothing user-written appears without review; no personal data stored beyond an optional pseudonym; takedown contact.
- **Freshness:** each entry has `checked_at` and `game_version`; after a patch, affected entries are queued; older than 60 days shows a warning.

## 6. Data model
| Table (JSON files) | Fields |
|---|---|
| `entry` | id, slug, type (vehicle, secret, cheat, guide), title, summary, body, category, tags, confidence, game_version, platforms, created_at, checked_at, status, related_entries |
| `vehicle` (extends entry) | class, how_to_get, location_text, location_image, price, customisation, test_values |
| `secret` (extends entry) | area, steps, requirements, spoiler_level |
| `source` | id, entry_id, kind (official, own test, community, press), url, author, published_at, accessed_at |
| `evidence` | id, entry_id, media, tester, tested_at, version, result, rights |
| `correction` | id, entry_id, date, before, after, reason, reported_by |
| `submission` | id, type, text, video_url, pseudonym, received_at, decision, entry_id |
| `video_link` | entry_id, platform, url |

Publication check: confidence is not RUMEUR; at least one source; evidence required for CONFIRMÉ (unless official) and TESTÉ; media has usable rights.

## 7. Legal points before launch (not legal advice)
- Unofficial fan project: say so; own logo; no Rockstar logo, official artwork, extracted map or leaked material.
- Rockstar's [copyright policy page](https://support.rockstargames.com/articles/200153756/Policy-on-posting-copyrighted-Rockstar-Games-material) describes occasional **non-commercial** use of game content by fans. It does not settle advertising on a fan site. Get an answer (copyright@take2games.com or a lawyer) **before** any monetisation; the question also concerns video monetisation.
- Third-party clips and screenshots: "credited" is not permission. On the site use only our own, licensed or permitted media.
- France: mentions légales, GDPR notice, consent before non-essential cookies, clear affiliate and sponsorship disclosure.

## 8. Costs (estimates, verify before buying)
| Item | MVP | If it grows |
|---|---|---|
| Domain | about €10–20 a year | same |
| Hosting, search, build | €0 | €0–25 a month |
| Analytics (cookieless, free tier) and Search Console | €0 | €0–10 a month |
| Map tiles and storage | none | unknown until designed |
| Game, console, capture (for testing) | already owned or not: **to confirm** | — |
| Your time: setup | 20–30 hours | — |
| Your time: 50 entries with testing | 40–75 hours | 4–8 hours a week upkeep |

Monetisation, in order, only after the legal answer: clearly disclosed affiliate links (hardware), sponsorship, then ads once traffic justifies them. No revenue is assumed.

## 9. Roadmap
| Step | Work | Gate to continue |
|---|---|---|
| 0. Validate, weeks 1–3 | 10 videos each on vehicles and secrets; ask for questions in captions; a one-page index of 10 entries; check Trends FR | At least 20 videos with 24 h readings, one theme's median ≥1.3 × channel median, 30+ distinct viewer questions, someone able to test in game |
| 1. MVP, weeks 4–7 | Schema, generator, 50 entries, search, legal pages | Definition of done met |
| 2. Measure, weeks 8–12 | Search Console, search terms, corrections | 1,000 search visits a month, or growth three weeks running; error rate under 5% |
| 3. Expand, months 4–6 | Most requested feature; submissions form | Weekly upkeep affordable |
| 4. Map and monetisation | Only if requested and legally cleared | — |

If gate 0 fails, stay a video brand.

## 10. Risks
No one testing in game; a big competitor covers the same facts; patches make entries wrong; Rockstar objects to commercial use; upkeep competes with daily video production.

## Sources checked (27 Nov 2026, search summaries)
[State of Leonida map coverage](https://www.notebookcheck.net/GTA-6-New-map-shows-Leonida-in-unprecedented-detail-and-smaller-than-expected.1404443.0.html) · [Cloudflare Pages limits](https://developers.cloudflare.com/pages/platform/limits) · [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/) · [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
