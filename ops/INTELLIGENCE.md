# VICECITY INTEL — content intelligence engine (Phase 4, 26 Nov 2026)

`cloud/intelligence.py` analyses footage, scores it and writes a French creative brief. The engine runs it every 3 hours.

## Analysis (measured from the file)
Suggested start and end (6–22 s), excitement peaks, sound bursts, large scene changes, dead time, weak or slow opening, darkness, resolution, frame rate, bitrate, speech and language (Whisper).

## Score (weights in `config/scoring.json`)
| Criterion | How |
|---|---|
| First-second impact, visual clarity, source quality | measured |
| Hook, entertainment, emotion, replayability, share potential, French relevance, category | heuristic |
| Originality, storytelling | only after a review; otherwise left out of the total |

Views count for at most 2 points inside share potential. A "reject" review caps the total at 3.

## Test on real decisions: the automatic score does not work as a judge
Blind test on 30 clips we accepted and 13 we rejected: AUC **0.39** (0.5 is a coin toss). Mean 6.94 accepted, 7.12 rejected. The top 10 unused clips by automatic score were checked by eye: 10 of 10 rejected (adult scenes, walking, calm driving, one non-GTA 6 clip). With those 10 added to the rejected set, `evaluate` gives AUC 0.29 (30 against 23); that figure leans low because the 10 were picked for their high score.

Why: loudness and motion do not tell an event from music, dancing, talking or camera movement. The accepted set had already passed a motion filter, so the sample is also biased. The scale was widened once so scores no longer bunch near the top; weights were not tuned to the labels.

**Use the automatic part for** cut points, dead time, quality warnings and speech. **Do not use the total to choose videos** without a review.

## Reviews
`db/reviews.json`, keyed by content id: `verdict` (keep/reject), `action_fr` (what happens), `hooks_fr`, optional scores for originality, storytelling, entertainment, emotion, hook. Reviews override heuristics and make the French brief specific. Written today by Claude from frame sheets (stills: sound and timing were not judged).

## French brief
Treatment (reaction, action cut, investigation, slow reveal), series, 3 hooks, title, description, caption, narration for the two narrated treatments, CTA, timed editing steps, music mood and licensed library picks. Without a review the hooks are generic category templates and are marked "needs review". Narration is text only; no voice is generated.

## Refine later
`python cloud/intelligence.py evaluate` repeats the blind test. Once published videos have analytics (Phase 7), fit weights against retention and shares.

## What would fix the judging
A vision model that watches the frames (Claude API key as a repository secret, small cost per clip). Not connected.

## Commands
```
python cloud/intelligence.py analyse --limit 20
python cloud/intelligence.py rank
python cloud/intelligence.py brief VCI-xxxxxxxxxx
python cloud/intelligence.py evaluate
python cloud/intelligence.py dashboard
```
