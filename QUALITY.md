# Quality bar: nothing ships unless it clears this

Goal: every video is a premium, watch-to-the-end short, not a filler clip. The cloud only posts videos that were
built from vetted material, passed the automatic gates, and (for each new template or batch) were reviewed frame
by frame before entering the queue.

## 1. Source material (vetted, never raw)
- Only official 4K footage (Rockstar trailers, official releases). Every shot is reviewed by eye and tagged
  (time of day, subject, mood, vehicle/character, location). Shots with watermarks ("Captured on PS5"), ratings
  cards, logos, black frames, or suggestive content are excluded permanently.
- Minimum shot length 1.8 s, native speed whenever possible (slow motion only down to 0.8x).
- Stream captures from third parties are not used in premium videos.

## 2. Every video has a point
Each video has one angle and one payoff. Examples: "Golden hour in Leonida", "Every vehicle in Trailer 2",
"7 details you missed in the Launch Trailer", "Vice City: day to night", "Jason and Lucia, in 25 seconds".
Facts on screen come only from official sources and are written in the database before use. No filler.

## 3. Craft
- Hook in the first 1.5 s: the single strongest shot plus a short title; no slow intros.
- Cuts land on the music (beat or phrase), varied transitions, speed ramps on action, consistent grade,
  bloom, fine grain, vignette; on-screen text inside safe zones; a clean ending that loops back.
- Music: cleared tracks only (CC0 or platform library). Famous commercial songs are added only inside TikTok's
  own library, never baked into files.
- Length 20 to 35 s, 1080x1920, 30 fps.

## 4. Automatic gates (a video that fails is regenerated with other shots, or dropped)
- No black or frozen frames longer than 0.3 s (ffmpeg blackdetect / freezedetect).
- Loudness about -14 LUFS, no clipping; audio present for the whole duration.
- Size at most 9.5 MB for the upload tools, 1080x1920, 24 to 35 s.
- No shot used in a video posted in the last 7 days; no template twice in a row; unique title and caption.

## 5. Human-grade review
- Every new template and every new batch is rendered, turned into a contact sheet and checked frame by frame
  before it is added to `queue/manifest.json`. Contact sheets are stored in `review/`.

## 6. Learn
- Views, likes and watch time per video are logged twice a day; the best templates, shots, hooks and music
  get more weight, the worst are retired.

## Hard rule: unique scenes
Every video uses its own GTA 6 shots. A shot (or scene) used in one video is never used in another. `trailer_montage.py --id <video>` checks `shots_used.json` and refuses any overlap. If the clean-shot pool runs out, source more official footage instead of reusing. No filler videos.
