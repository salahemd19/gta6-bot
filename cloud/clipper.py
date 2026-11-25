"""GTA 6 stream clipper: Kick VOD/clip (or local file) -> captioned vertical clips.

Usage:
  python clipper.py <kick-url-or-file> [--count 10] [--len 30] [--out out]

Steps: download -> loudness-based hype detection -> pick top N non-overlapping
windows -> Whisper captions -> 9:16 render (blurred background, captions burned in).
Only use streams you have permission to clip.
"""
import argparse, subprocess, sys, wave, json
from pathlib import Path
import numpy as np


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"FAILED: {' '.join(map(str, cmd))}\n{r.stderr[-1500:]}")
    return r


def download(src, work):
    if Path(src).exists():
        return Path(src)
    out = work / "source.mp4"
    run(["yt-dlp", "-f", "best[height<=1080]/best", "--merge-output-format", "mp4",
         "-o", str(out), src])
    return out


def extract_audio(video, wav):
    run(["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav)])


HYPE_WORDS = {"non", "oh", "wow", "regarde", "regardez", "attends", "attention", "incroyable", "dingue",
              "fou", "folle", "malade", "énorme", "enorme", "gg", "bravo", "mdr", "ptdr", "lol", "haha",
              "impossible", "sérieux", "serieux", "gagné", "perdu", "mort", "explose", "boom", "crash",
              "accident", "vite", "allez", "quoi", "comment", "jamais", "trop", "ouf", "wesh"}
LAUGH = ("haha", "hihi", "mdr", "ptdr", "lol")
HOOKS = ["ATTENDS LA FIN", "REGARDE BIEN ÇA", "TU AURAIS FAIT QUOI ?", "ÇA PART EN LIVE", "LA SUITE EST FOLLE"]


def find_candidates(wav, count, length):
    """Top `count` non-overlapping windows by loudness + sudden spikes; returns [(start, end, loud_score)]."""
    with wave.open(str(wav)) as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    step = sr // 2  # 0.5s frames
    n = len(data) // step
    rms = np.sqrt((data[: n * step].reshape(n, step) ** 2).mean(axis=1))
    rms = rms / (np.percentile(rms, 95) + 1e-9)
    win = int(length * 2)
    if n <= win:
        return [(0.0, n / 2, 1.0)]
    spikes = np.clip(np.diff(rms, prepend=rms[0]), 0, None)
    score_f = rms + 2 * spikes
    cs = np.concatenate([[0], np.cumsum(score_f)])
    scores = (cs[win:] - cs[:-win]) / win
    picks, taken = [], np.zeros(len(scores), bool)
    total = n / 2
    for i in np.argsort(scores)[::-1]:
        if taken[i]:
            continue
        peak = i + int(np.argmax(score_f[i:i + win]))  # loudest/spikiest half-second in the window
        start = min(max(0.0, peak / 2 - 5.0), max(0.0, total - length))  # open ~5 s before the peak
        picks.append((start, start + length, float(scores[i])))
        taken[max(0, i - win): i + win] = True
        if len(picks) == count:
            break
    return sorted(picks)


def hype_score(words, loud, length):
    """Combine loudness with what is actually said: hype words, exclamations, speech rate, laughter."""
    text = " ".join(w["word"].strip().lower() for w in words)
    toks = [t.strip(".,!?;:'\"-") for t in text.split()]
    kw = sum(t in HYPE_WORDS for t in toks)
    excl = text.count("!") + text.count("?")
    wps = len(words) / max(length, 1)
    laugh = any(l in text for l in LAUGH)
    score = loud + 0.15 * kw + 0.05 * excl + 0.5 * min(wps / 3.0, 1.0) + (0.3 if laugh else 0.0)
    if wps < 0.8:
        score -= 0.5  # mostly silence / music: weak moment
    return score, {"hype_words": kw, "excl": excl, "words_per_sec": round(wps, 2), "laugh": laugh}


def ass_time(t):
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def make_ass(words, path, hook=None):
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
            "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,"
            "Bold,Outline,Shadow,Alignment,MarginV\n"
            "Style: Default,Arial Black,84,&H00FFFFFF,&H00000000,&H00000000,1,6,0,2,420\n"
            "Style: Hook,Arial Black,96,&H0000F0FF,&H00000000,&H00000000,1,8,0,8,260\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Text\n")
    if hook:
        head += f"Dialogue: 1,0:00:00.00,0:00:02.60,Hook,{hook}\n"
    lines, chunk = [], []
    for w in words:
        chunk.append(w)
        if len(chunk) == 3:
            lines.append(chunk); chunk = []
    if chunk:
        lines.append(chunk)
    body = ""
    for c in lines:
        text = " ".join(w["word"].strip().upper() for w in c)
        body += f"Dialogue: 0,{ass_time(c[0]['start'])},{ass_time(c[-1]['end'])},Default,{text}\n"
    path.write_text(head + body, encoding="utf-8")


def transcribe(model, wav_clip, lang=None):
    with wave.open(str(wav_clip)) as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    segs, _ = model.transcribe(audio, word_timestamps=True, vad_filter=True, language=lang)
    return [{"word": w.word, "start": w.start, "end": w.end} for s in segs for w in s.words]


def render(video, start, length, ass, out_file, cwd):
    # Punchier edit: slow zoom-in on the gameplay, extra colour/contrast, yellow progress bar, blurred backdrop.
    # v2: the gameplay fills most of the 9:16 frame (centre 3:4 crop, 1080x1440) instead of a small 16:9 strip;
    # sharpened, slow punch-in, stronger colour, vignette; blurred backdrop only fills the top/bottom bands.
    vf = ("[0:v]fps=30,split[a][b];"
          "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5,eq=brightness=-0.08[bg];"
          "[b]crop=ih*3/4:ih,scale=1080:1440:flags=lanczos,unsharp=5:5:0.9,"
          "zoompan=z='min(1.0+0.0006*on,1.12)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1440:fps=30,"
          "eq=saturation=1.3:contrast=1.1[fg];"
          "[bg][fg]overlay=(W-w)/2:(H-h)/2,vignette=PI/6[base];"
          f"[base][1:v]overlay=x='-w+w*t/{length:.2f}':y=1890:eval=frame[bar];"
          f"[bar]subtitles={ass.name}[v]")
    run(["ffmpeg", "-y", "-ss", str(start), "-t", str(length), "-i", str(video),
         "-f", "lavfi", "-i", f"color=c=0xFFD400:s=1080x22:r=30:d={length:.2f}",
         "-filter_complex", vf, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k", out_file.name],
        cwd=cwd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--len", type=int, default=30)
    ap.add_argument("--out", default="out")
    ap.add_argument("--model", default="base")
    ap.add_argument("--chat", default=None, help="chat.json from chat_signal.fetch: boost clips where the live chat reacted")
    ap.add_argument("--min-score", type=float, default=1.4, help="quality gate: minimum hype score for a clip to be rendered")
    ap.add_argument("--lang", default=None, help="speech language for captions, e.g. fr (auto-detect if omitted)")
    a = ap.parse_args()

    out = Path(a.out).resolve(); out.mkdir(exist_ok=True)
    work = out / "_work"; work.mkdir(exist_ok=True)

    print("1/4 downloading...")
    video = download(a.source, work).resolve()
    print("2/4 detecting hype moments...")
    wav = work / "audio.wav"
    extract_audio(video, wav)
    candidates = find_candidates(wav, a.count * 3, a.len)  # over-generate, then re-rank by content
    chat = None
    if a.chat and Path(a.chat).exists():  # chat reaction: extra candidates at chat spikes + score bonus
        import chat_signal
        chat = json.loads(Path(a.chat).read_text(encoding="utf-8"))
        extra = [c for c in chat_signal.spike_windows(chat, a.len) if all(abs(c[0] - x[0]) > 10 for x in candidates)]
        candidates += extra
        print(f"   chat: {len(chat['offsets'])} messages, +{len(extra)} spike candidates")

    print("3/4 loading Whisper and scoring candidates...")
    from faster_whisper import WhisperModel
    model = WhisperModel(a.model, compute_type="int8")
    scored = []
    for j, (s, e, loud) in enumerate(candidates):
        cw = work / f"cand{j:02d}.wav"
        run(["ffmpeg", "-y", "-ss", str(s), "-t", str(e - s), "-i", str(wav), str(cw)])
        words = transcribe(model, cw, a.lang)
        sc, feats = hype_score(words, loud, e - s)
        if chat:
            import chat_signal
            cb = chat_signal.window_boost(chat, s, e)
            sc += cb
            feats["chat_boost"] = cb
        scored.append((sc, s, e, words, feats))
    # QUALITY GATE: only genuinely strong moments (loud + spoken reaction) are rendered; weak ones are dropped.
    EN = {"the", "and", "you", "that", "this", "with", "for", "they", "was", "are", "have", "what", "your", "but", "not", "he", "she", "it's", "i'm", "don't", "like", "into", "just"}

    def english_game_audio(words):  # the game's own English dialogue, not the French streamer reacting
        toks = [w["word"].strip().lower().strip(".,!?;:'\"-") for w in words]
        return bool(toks) and sum(t in EN for t in toks) / len(toks) > 0.22

    # the English-dialogue filter only makes sense for French streams (English there = the game's own audio)
    strong = [x for x in scored if x[0] >= a.min_score and not (a.lang == "fr" and english_game_audio(x[3]))]
    print(f"   {len(strong)}/{len(scored)} candidates pass the quality gate (score >= {a.min_score})")
    best = sorted(sorted(strong, key=lambda x: -x[0])[: a.count], key=lambda x: x[1])

    print("4/4 rendering clips...")
    hooks = list(HOOKS)
    try:  # best-performing hooks first, learned from past results (learn.py)
        learned = json.loads(Path("preferences.json").read_text(encoding="utf-8")).get("hooks_order", [])
        hooks = [h for h in learned if h in HOOKS] + [h for h in HOOKS if h not in learned]
    except Exception:
        pass
    meta = []
    for i, (sc, s, e, words, feats) in enumerate(best, 1):
        hook = hooks[(i - 1) % len(hooks)]
        ass = out / f"clip{i:02d}.ass"
        make_ass(words, ass, hook)
        mp4 = out / f"clip{i:02d}.mp4"
        render(video, s, e - s, ass, mp4, cwd=out)
        meta.append({"file": mp4.name, "start": s, "end": e, "score": round(sc, 3), "hook": hook,
                     "features": feats, "transcript": " ".join(w["word"].strip() for w in words)})
        print(f"  {mp4.name}  [{s:.0f}s-{e:.0f}s] score={sc:.2f} {feats}")
    (out / "clips.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Done. {len(meta)} clips in {out}")


if __name__ == "__main__":
    main()
