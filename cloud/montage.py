"""Compilation builder: the 5 strongest moments across many live GTA 6 streams -> one 30 s vertical countdown video.

Every second must be action: each stream is scanned for short audio/chat peaks, every peak is checked on screen
(motion, frozen frames, cutscene letterbox), and only the best 5 make the cut (max 2 per streamer, never two from the
same moment). No speech subtitles: French title, countdown and creator credit only.
"""
import json
import subprocess
import wave
from pathlib import Path

import numpy as np

import chat_signal
from clipper import extract_audio, visual

SEG = 5.5          # seconds per moment
PRE = 2.0          # open this long before the peak
TITLES = ["LES 5 MOMENTS LES PLUS FOUS", "TOP 5 GTA 6 DU JOUR", "5 MOMENTS IRRÉELS SUR GTA 6",
          "GTA 6 : LE TOP 5 DU JOUR", "ILS ONT FAIT ÇA SUR GTA 6"]


def peaks(video, chat, slug, per_stream=10):
    """Candidate moments in one capture: loud, sudden audio peaks (shots, crashes, screams) plus chat spikes."""
    wav = Path(video).with_name("peaks.wav")
    extract_audio(video, wav)
    with wave.open(str(wav)) as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    step = sr // 4  # 0.25 s frames
    n = len(data) // step
    if n < 40:
        return []
    rms = np.sqrt((data[: n * step].reshape(n, step) ** 2).mean(axis=1))
    rms = rms / (np.percentile(rms, 95) + 1e-9)
    base = np.convolve(rms, np.ones(20) / 20, mode="same")   # 5 s context
    jump = np.clip(rms - base, 0, None)                      # sudden bursts above the surrounding level
    score = rms + 3 * jump
    total = n / 4
    out, taken = [], np.zeros(n, bool)
    for i in np.argsort(score)[::-1]:
        if taken[i] or len(out) >= per_stream:
            continue
        t = i / 4
        start = min(max(0.0, t - PRE), max(0.0, total - SEG))
        taken[max(0, i - 80): i + 80] = True                  # moments at least 20 s apart
        out.append({"slug": slug, "video": str(video), "start": start, "peak": float(score[i])})
    for c in chat_signal.spike_windows(chat, SEG, count=4) if chat else []:
        if all(abs(c[0] - o["start"]) > 15 for o in out):
            out.append({"slug": slug, "video": str(video), "start": float(c[0]), "peak": 1.0})
    for o in out:
        o["chat"] = chat_signal.window_boost(chat, o["start"], o["start"] + SEG) if chat else 0.0
    return out


def pick(cands, k=5):
    """Check candidates on screen, best first, until k strong moments (max 2 per streamer)."""
    cands.sort(key=lambda c: -(c["peak"] + c["chat"]))
    chosen, per = [], {}
    for c in cands:
        if len(chosen) == k:
            break
        if per.get(c["slug"], 0) >= 2:
            continue
        v = visual(c["video"], c["start"], SEG)
        if v["motion"] < 13 or v["still"] > 0.12 or v["letterbox"] > 0.3:
            continue
        c.update(v)
        c["score"] = round(c["peak"] + c["chat"] + 0.05 * min(v["motion"], 30), 3)
        chosen.append(c)
        per[c["slug"]] = per.get(c["slug"], 0) + 1
    return chosen


def _ass(path, title, rank, slug):
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\n"
            "Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,Outline,Shadow,Alignment,MarginL,MarginR,MarginV\n"
            "Style: Title,Anton,88,&H00FFFFFF,&H00000000,&H00000000,0,6,0,8,40,40,70\n"
            "Style: Rank,Anton,190,&H0000D4FF,&H00000000,&H00000000,0,9,0,7,50,40,250\n"
            "Style: Credit,Anton,54,&H00FFFFFF,&H00000000,&H00000000,0,4,0,2,40,40,150\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Text\n")
    end = "0:00:09.00"
    path.write_text(head + f"Dialogue: 1,0:00:00.00,{end},Title,{title}\n"
                    f"Dialogue: 1,0:00:00.00,{end},Rank,#{rank}\n"
                    f"Dialogue: 1,0:00:00.00,{end},Credit,@{slug} · Kick\n", encoding="utf-8")


def render(moments, title, out, work, fonts, music=None):
    """Countdown order: #5 is the 2nd strongest (strong hook), #1 the strongest (payoff)."""
    by = sorted(moments, key=lambda m: -m["score"])
    order = [by[1]] + by[2:][::-1] + [by[0]] if len(by) > 2 else by[::-1]
    parts = []
    for i, m in enumerate(order):
        rank = len(order) - i
        ass = work / f"seg{i}.ass"
        _ass(ass, title, rank, m["slug"])
        seg = work / f"seg{i}.mp4"
        vf = ("[0:v]fps=30,split[a][b];"
              "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5,eq=brightness=-0.12[bg];"
              "[b]crop=ih*3/4:ih,scale=1080:1440:flags=lanczos,unsharp=5:5:0.8,eq=saturation=1.25:contrast=1.08[fg];"
              f"[bg][fg]overlay=0:240,{'fade=in:st=0:d=0.15:color=white,' if i else ''}subtitles={ass.name}:fontsdir={fonts}[v];"
              "[0:a]aresample=48000,loudnorm=I=-14:TP=-1.5:LRA=11,afade=in:d=0.05[a]")
        r = subprocess.run(["ffmpeg", "-y", "-ss", f"{m['start']:.2f}", "-t", str(m.get("len", SEG)), "-i", m["video"],
                            "-filter_complex", vf, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                            "-ac", "2", seg.name], cwd=work, capture_output=True, text=True)
        if r.returncode:
            print("segment failed:", r.stderr[-400:])
            continue
        parts.append(seg)
    (work / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    raw = work / "raw.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", str(raw)],
                   cwd=work, capture_output=True, text=True)
    brand(raw, out, [float(m.get("len", SEG)) for m in order], music)
    return [dict(o, rank=len(order) - i) for i, o in enumerate(order)] if out.exists() else []


SFX = Path(__file__).resolve().parent.parent / "music" / "sfx"


def brand(raw, out, lens, music=None):
    """VICECITY INTEL sound identity on top of the game audio: intro on the hook, whoosh on every cut, reveal on #1,
    outro at the end; optional licensed music bed (path, start_s, volume_db) from music/recommend.py."""
    cuts = [sum(lens[:i]) for i in range(1, len(lens))]
    total = sum(lens)
    cues = [("intro", 0.0, -8)] + [("transition", max(0.0, c - 0.18), -12) for c in cuts[:-1]]
    if cuts:
        cues.append(("reveal", max(0.0, cuts[-1] - 0.1), -8))
    cues.append(("outro", max(0.0, total - 1.0), -10))
    ins, parts = ["-i", str(raw)], []
    for k, (name, t, db) in enumerate(cues, 1):
        ins += ["-i", str(SFX / f"vci_{name}.wav")]
        ms = int(t * 1000)
        parts.append(f"[{k}:a]volume={db}dB,adelay={ms}|{ms}[s{k}]")
    n = len(cues) + 1
    mix = "[0:a]" + "".join(f"[s{k}]" for k in range(1, n))
    if music:
        path, start, db = music
        ins += ["-ss", str(start), "-i", str(path)]
        parts.append(f"[{n}:a]atrim=0:{total:.2f},asetpts=PTS-STARTPTS,volume={db}dB,afade=out:st={max(0, total - 1.5):.2f}:d=1.5[mb]")
        mix += "[mb]"
        n += 1
    fc = ";".join(parts + [f"{mix}amix=inputs={n}:duration=first:normalize=0,alimiter=limit=0.95[a]"])
    r = subprocess.run(["ffmpeg", "-y", *ins, "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)], capture_output=True, text=True)
    if r.returncode:  # never lose the video over the sound layer
        print("brand sound failed:", r.stderr[-300:])
        subprocess.run(["ffmpeg", "-y", "-i", str(raw), "-c", "copy", str(out)], capture_output=True)


def build(streams, out, work, fonts, title):
    """streams: [{'slug', 'video', 'chat'}] -> (out path, moments) or (None, [])."""
    cands = []
    for s in streams:
        chat = json.loads(Path(s["chat"]).read_text(encoding="utf-8")) if s.get("chat") and Path(s["chat"]).exists() else None
        try:
            cands += peaks(s["video"], chat, s["slug"])
        except Exception as e:  # noqa: BLE001
            print(s["slug"], "peak scan failed:", e)
    moments = pick(cands)
    print(f"{len(cands)} candidate moments, {len(moments)} kept:",
          [(m["slug"], round(m["start"]), m["motion"], m["score"]) for m in moments])
    if len(moments) < 4 or len({m["slug"] for m in moments}) < 2:
        return None, moments
    work.mkdir(parents=True, exist_ok=True)
    used = render(moments, title, out, work, fonts)
    return (out if used else None), used
