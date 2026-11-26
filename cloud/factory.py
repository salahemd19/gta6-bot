"""VICECITY INTEL production factory (Phase 5): approved candidate -> branded YouTube Short and TikTok exports.

  python cloud/factory.py candidates
  python cloud/factory.py produce VCI-a [VCI-b VCI-c] [--template police-intel] [--media DIR] [--id NAME] [--test]
  python cloud/factory.py check work/factory/<id>

Only footage that was watched and kept (db/reviews.json), has publishable rights and was never used can be exported.
Narration needs Piper (env PIPER_VOICE); without it the video is rendered with captions only and says so.
--test renders for checking the workflow: nothing is registered, output is marked not publishable. It never skips the rights gate.
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT / "music")]
import contentdb  # noqa: E402
import intelligence  # noqa: E402
import recommend  # noqa: E402

CFG = json.loads((ROOT / "config" / "templates.json").read_text(encoding="utf-8"))
OUT = ROOT / "work" / "factory"
REG = ROOT / "db" / "productions.json"
SFX = ROOT / "music" / "sfx"
MUSIC = ROOT / "music" / "files"  # local only, <track id>.mp3: licences do not allow redistributing the audio files
LOGO = ROOT / "docs" / "icon-1024.png"
W, H, FPS = 1080, 1920, 30


def run(cmd, cwd=None, check=True):
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr[-700:]}")
    return r


def template(name):
    t = CFG["templates"][name]
    return {**CFG["templates"][t["base"]], **t} if "base" in t else dict(t)


def registry():
    return json.loads(REG.read_text(encoding="utf-8")) if REG.exists() else []


def used_sources():
    return {s["content_id"] for p in registry() for s in p["sources"]}


# ------------------------------------------------------------------ 1. gate
def blockers(rec, rv, used):
    why = []
    if rec.get("rights") not in contentdb.PUBLISHABLE:
        why.append(f"rights not publishable ({rec.get('rights')})")
    if not rv or rv.get("verdict") != "keep" or not rv.get("action_fr") or not rv.get("hooks_fr"):
        why.append("not approved: no 'keep' review with French description and hooks")
    if rec.get("state") in ("rejected", "duplicated", "rights_unverified"):
        why.append(f"state {rec['state']}")
    if rec.get("authenticity") != "verified_by_review":
        why.append(f"authenticity {rec.get('authenticity')}")
    if rec.get("used_in") or rec["content_id"] in used:
        why.append("footage already used")
    return why


def index(db):
    return {r["content_id"]: r for r in db.values()}


# ------------------------------------------------------------------ 2-4. source, segment
def segment(rec, f, single, rv=None):
    a = rec.get("analysis") or intelligence.analyse_file(f, False)
    if (rv or {}).get("window"):  # the reviewer's own cut (skips menus or dead time seen by eye)
        s, e = rv["window"]
        return s, min(e, s + (22 if single else 6.5)), a
    if single:
        return a["start"], min(a["end"], a["start"] + 22), a
    inside = [p for p in a["peaks_s"] if a["start"] <= p <= a["end"]]
    start = max(a["start"], (inside[0] if inside else a["start"] + 3) - 2.5)
    start = max(0.0, min(start, a["end"] - 6.5))
    return start, min(a["end"], start + 6.5), a


# ------------------------------------------------------------------ 5-6. narration and French subtitles
def speak(text, wav):
    voice = os.environ.get("PIPER_VOICE")
    if not voice:
        return None
    r = run([sys.executable, "-m", "piper", "-m", voice, "--data-dir", os.environ.get("PIPER_DIR", "."), "-f", wav, "--",
             text], check=False)
    if r.returncode or not wav.exists():
        print("narration failed:", r.stderr[-300:])
        return None
    with wave.open(str(wav)) as w:
        return w.getnframes() / w.getframerate()


def chunks(text, start, end, max_words=4):
    """Split a line into short subtitle cues, timed in proportion to their length."""
    words = text.split()
    groups = [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]
    total, t, out = sum(len(g) for g in groups) or 1, start, []
    for g in groups:
        d = (end - start) * len(g) / total
        out.append((round(t, 2), round(t + d, 2), g))
        t += d
    return out


def french_speech(f, start, end):
    """Subtitle cues for speech that is really French. Other languages are not translated (no free translator wired)."""
    try:
        from faster_whisper import WhisperModel
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(end - start), "-i", str(f), "-ac", "1",
                              "-ar", "16000", "-f", "f32le", "-"], capture_output=True).stdout
        try:
            model = WhisperModel("base", device="cpu", compute_type="int8", local_files_only=True)
        except Exception:  # noqa: BLE001
            model = WhisperModel("base", device="cpu", compute_type="int8")
        segs, info = model.transcribe(np.frombuffer(pcm, np.float32).copy(), vad_filter=True, word_timestamps=True)
        if info.language != "fr" or info.language_probability < 0.7:
            return [], info.language
        cues = []
        for s in segs:
            words = list(s.words or [])
            for i in range(0, len(words), 4):
                g = words[i:i + 4]
                cues.append((g[0].start, g[-1].end, "".join(w.word for w in g).strip()))
        return cues, "fr"
    except Exception as e:  # noqa: BLE001
        print("speech subtitles skipped:", e)
        return [], None


# ------------------------------------------------------------------ 7. branding (ASS overlay)
def bgr(name):
    h = CFG["brand"][name].lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}"


def ts(t):
    return f"{int(t // 3600)}:{int(t // 60) % 60:02d}:{t % 60:05.2f}"


def clean(s):
    return re.sub(r"[{}\\\n]", " ", s).strip()


def ass_file(path, tpl, hook, subs, segs, total):
    acc, cy, mg, font = bgr(tpl["accent"]), bgr("cyan"), bgr("magenta"), CFG["brand"]["font"]

    def st(n, size, col, out, ow, al, mv, ml=60, box=1):
        return f"Style: {n},{font},{size},{col},{out},&H90000000,0,{ow},0,{al},{ml},60,{mv},{box}"
    head = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 0", "", "[V4+ Styles]",
            "Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,BorderStyle",
            st("Logo", 58, "&H00FFFFFF", "&H00000000", 3, 7, 62, 190),
            st("Badge", 52, "&H00120B0B", acc, 12, 8, 168, box=3),
            st("Hook", 118, "&H00FFFFFF", mg, 7, 5, 0), st("Sub", 84, "&H00FFFFFF", "&H00120B0B", 8, 2, 360),
            st("Credit", 46, "&H00FFFFFF", "&H00000000", 3, 2, 150), st("Rank", 180, cy, "&H00000000", 8, 7, 280),
            st("Cta", 70, "&H00FFFFFF", cy, 5, 2, 600), "", "[Events]",
            "Format: Layer,Start,End,Style,MarginL,MarginR,MarginV,Effect,Text"]
    ev = []

    def add(a, b, style, text, layer=1):
        ev.append(f"Dialogue: {layer},{ts(a)},{ts(b)},{style},0,0,0,,{text}")
    add(0, total, "Logo", f"VICECITY {{\\c{cy}&}}INTEL")
    add(0, total, "Badge", clean(tpl["badge"]))
    add(0, min(1.9, total), "Hook", "{\\fad(0,150)\\fscx80\\fscy80\\t(0,180,\\fscx100\\fscy100)}" + clean(hook), 3)
    for s in segs:
        add(s["at"], s["at"] + s["len"], "Credit", clean(f"@{s['creator']} · {s['platform'].title()}"))
        if s.get("rank"):
            add(s["at"], s["at"] + s["len"], "Rank", f"#{s['rank']}")
    for a, b, text in subs:
        add(a, b, "Sub", clean(text).upper(), 2)
    if not any(a >= total - 2.6 and tpl["cta"].startswith(text) for a, _, text in subs):  # never shown twice
        add(max(0, total - 2.0), total, "Cta", "{\\fad(150,0)}" + clean(tpl["cta"]), 2)
    path.write_text("\n".join(head + ev) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ 8-11. edit, mix, export
def cut(src, start, length, peak, tpl, flash, out, dark=False):
    z = tpl["zoom"]
    lift = "eq=gamma=1.35," if dark else ""
    p = max(0.0, (peak if peak is not None else start + length / 2) - start)
    vf = (f"[0:v]fps={FPS},split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:5,"
          f"eq=brightness=-0.22[bg];[b]crop='min(iw,ih*3/4)':ih,scale=1080:1440:flags=lanczos,{lift}{tpl['grade']},unsharp=5:5:0.7,"
          f"scale=w='trunc(540*(1+{z}*between(t,{p:.2f},{p + 0.8:.2f})))*2':h=-2:eval=frame,crop=1080:1440[fg];"
          f"[bg][fg]overlay=0:260{',fade=in:st=0:d=0.15:color=white' if flash else ''},format=yuv420p,setsar=1[v];"
          f"[0:a]aresample=48000,aformat=channel_layouts=stereo,loudnorm=I=-16:TP=-2:LRA=11,aresample=48000,apad,"
          f"atrim=0:{length:.3f},afade=in:d=0.05,afade=out:st={length - 0.08:.3f}:d=0.08[a]")
    run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", src, "-filter_complex", vf, "-map", "[v]",
         "-map", "[a]", "-t", f"{length:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-c:a", "pcm_s16le", out])


def meta_track(t, platform):
    return {"id": t["id"], "title": t["title"], "artist": t["artist"], "source": t["source"], "licence": t.get("licence_evidence"),
            "permitted": t["platforms"][platform], "platforms": t["platforms"], "attribution": t["attribution"],
            "conditions": t.get("conditions"), "monetization": t.get("monetization")}


def music_for(tpl, platform, duration):
    """Library only. Returns (file to mix or None, metadata). TikTok in-app sounds are never baked into the file."""
    recs = recommend.recommend(tpl["music"], platform, duration, n=8)
    tracks = {t["id"]: t for t in recommend.load()[0]["tracks"]}
    for r in recs:
        t, f = tracks[r["id"]], MUSIC / f"{r['id']}.mp3"
        if t["platforms"][platform] == "APPROVED" and f.exists():
            return (f, r["start_s"], r["volume_db"]), {"mode": "mixed into file", **meta_track(t, platform)}
    if not recs:
        return None, {"mode": "none: no approved track"}
    t = tracks[recs[0]["id"]]
    mode = "add in TikTok's sound picker" if t["platforms"][platform] == "IN_APP_ONLY" else "NOT mixed: audio file not on this machine"
    return None, {"mode": mode, **meta_track(t, platform), "alternatives": [r["track"] for r in recs[1:3]]}


def export(work, base, total, voices, music, cuts, tpl, out):
    ins, fc, n = ["-i", base.name], [], [1]

    def add(*args):
        ins.extend(str(a) for a in args)
        n[0] += 1
        return n[0] - 1
    bar = add("-f", "lavfi", "-i", f"color=c={CFG['brand'][tpl['accent']]}:s={W}x12:r={FPS}:d={total:.2f}")
    v = "[0:v]"
    if LOGO.exists():
        logo = add("-i", LOGO)
        fc.append(f"[{logo}:v]scale=110:110[lg];{v}[lg]overlay=60:40[v1]")
        v = "[v1]"
    fc.append(f"{v}[{bar}:v]overlay=x='-{W}+{W}*t/{total:.2f}':y=1908:eof_action=pass,subtitles=brand.ass:fontsdir=.[v]")
    layers = []
    cues = [("intro", 0.0, -9)] + [("transition", c - 0.18, -13) for c in cuts[:-1]] + \
           ([("reveal", cuts[-1] - 0.1, -9)] if cuts else []) + [("outro", total - 1.0, -11)]
    for name, t, db in cues:
        k = add("-i", SFX / f"vci_{name}.wav")
        ms = max(0, int(t * 1000))
        fc.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={db}dB,adelay={ms}|{ms}[l{k}]")
        layers.append(f"[l{k}]")
    voice = []
    for t, wav, tempo in voices:
        k = add("-i", wav)
        ms = int(t * 1000)
        fc.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,atempo={tempo:.3f},volume=3dB,adelay={ms}|{ms}[n{k}]")
        voice.append(f"[n{k}]")
    bed = ["[0:a]"]
    if music:
        f, start, db = music
        k = add("-ss", start, "-i", f)
        fc.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.2f},asetpts=PTS-STARTPTS,volume={db}dB,"
                  f"afade=out:st={max(0, total - 1.5):.2f}:d=1.5[mus]")
        bed.append("[mus]")
    fc.append(f"{''.join(bed)}amix=inputs={len(bed)}:duration=first:normalize=0[bed]")
    base_a = "[bed]"
    if voice:  # speech on top: game and music duck while the narrator talks
        fc.append(f"{''.join(voice)}amix=inputs={len(voice)}:duration=longest:normalize=0,apad,atrim=0:{total:.2f},asplit[vo][key]")
        fc.append("[bed][key]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=300[duck]")
        base_a, layers = "[duck]", layers + ["[vo]"]
    fc.append(f"{base_a}{''.join(layers)}amix=inputs={len(layers) + 1}:duration=first:normalize=0,"
              "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
    run(["ffmpeg", "-y", *ins, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
         "-r", FPS, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-maxrate", "8M", "-bufsize", "16M",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out.resolve()],
        cwd=work)


# ------------------------------------------------------------------ 12. quality control
def qc(video, meta):
    """Every check returns pass/warn/fail; one fail blocks the production."""
    res = {}

    def put(name, ok, detail, level="fail"):
        res[name] = {"result": "pass" if ok else level, "detail": detail}
    p = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", video]).stdout)
    v = next((s for s in p["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in p["streams"] if s["codec_type"] == "audio"), None)
    dur = float(p["format"]["duration"])
    put("resolution", (v.get("width"), v.get("height")) == (W, H), f"{v.get('width')}x{v.get('height')}")
    put("aspect_ratio", bool(v.get("height")) and abs(v["width"] / v["height"] - 9 / 16) < 0.01, "9:16 expected")
    put("codec", v.get("codec_name") == "h264" and v.get("r_frame_rate") == "30/1", f"{v.get('codec_name')} {v.get('r_frame_rate')}")
    put("duration", 6 <= dur <= 60 and abs(dur - meta["duration_s"]) < 0.6, f"{dur:.2f}s, planned {meta['duration_s']:.2f}s")
    put("audio_stream", bool(a), a and a.get("codec_name"))
    dec = run(["ffmpeg", "-v", "error", "-i", video, "-f", "null", "-"], check=False)
    put("decode_errors", dec.returncode == 0 and not dec.stderr.strip(), dec.stderr[:200] or "none")
    log = run(["ffmpeg", "-i", video, "-af", "ebur128=peak=true,silencedetect=n=-45dB:d=1.5", "-vf",
               "blackdetect=d=0.3:pix_th=0.08,freezedetect=n=0.003:d=1.5", "-f", "null", "-"], check=False).stderr
    summary = log[log.rfind("Summary:"):]
    lufs = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    peak = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
    lufs, peak = float(lufs.group(1)) if lufs else None, float(peak.group(1)) if peak else None
    put("loudness", lufs is not None and -16.5 <= lufs <= -12, f"{lufs} LUFS (target -14)")
    put("true_peak", peak is not None and peak <= -0.5, f"{peak} dBTP")
    put("silence", "silence_start" not in log, f"{log.count('silence_start')} gaps over 1.5s", "warn")
    put("black_frames", "black_start" not in log, f"{log.count('black_start')} black stretches")
    put("frozen_frames", "freeze_start" not in log, f"{log.count('freeze_start')} frozen stretches", "warn")
    subs = meta["subtitles"]
    bad = [s for i, s in enumerate(subs) if s[0] < 0 or s[1] <= s[0] or s[1] > dur + 0.1 or (i and s[0] < subs[i - 1][1] - 0.05)]
    put("subtitle_timing", not bad, f"{len(subs)} cues, {len(bad)} out of range or overlapping")
    fast = [s for s in subs if len(s[2]) / max(0.01, s[1] - s[0]) > 25]
    put("subtitle_reading_speed", not fast, f"{len(fast)} cues over 25 characters per second", "warn")
    put("narration", meta["narration"]["status"] == "generated", meta["narration"]["status"], "warn")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(video), "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    cyan = 0
    if len(raw) == W * H * 3:
        top = np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(int)[30:260]
        cyan = int(((top[..., 0] < 90) & (top[..., 1] > 170) & (top[..., 2] > 190)).sum())
    put("branding", cyan > 500, f"{cyan} brand-cyan pixels in the header")
    put("source_resolution", all(s["height"] >= 720 for s in meta["sources"]), str([s["height"] for s in meta["sources"]]), "warn")
    put("duplicate_footage", not meta["duplicates"], meta["duplicates"] or "none")
    m = meta["music"]
    put("music_licence", m.get("mode", "").startswith(("none", "add in", "NOT")) or m.get("permitted") == "APPROVED", m.get("mode"))
    put("music_present", m.get("mode") == "mixed into file", m.get("mode"), "warn")
    put("attribution", not str(m.get("attribution", "")).startswith("CHECK"), m.get("attribution", "none"), "warn")
    return res


def distance(a, b):
    return bin(int(str(a), 16) ^ int(str(b), 16)).count("1")


def duplicates(hashes, ids):
    out = [f"segments {j + 1} and {i + 1} look identical" for i in range(len(hashes)) for j in range(i)
           if distance(hashes[i], hashes[j]) <= 6]
    for p in registry():
        for s in p["sources"]:
            for i, h in enumerate(hashes):
                if s["content_id"] == ids[i] or (s.get("dhash") and distance(h, s["dhash"]) <= 6):
                    out.append(f"{ids[i]} already in {p['id']}")
    return sorted(set(out))


def frame_hash(f, at):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(f), "-frames:v", "1", "-vf",
                          "scale=9:8,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    g = np.frombuffer(raw[:72], np.uint8).reshape(8, 9)
    return f"{int(''.join('1' if x else '0' for x in (g[:, 1:] > g[:, :-1]).ravel()), 2):016x}"


# ------------------------------------------------------------------ pipeline
def produce(ids, name=None, tpl_name=None, media=None, test=False):
    started = dt.datetime.now()
    db = contentdb.load()
    by, revs, used = index(db), intelligence.reviews(), used_sources()
    blocked = {}
    for cid in ids:
        if cid not in by:
            blocked[cid] = ["unknown content id"]
            continue
        why = blockers(by[cid], revs.get(cid), used)
        if test:
            why = [w for w in why if w != "footage already used"]
        if why:
            blocked[cid] = why
    if blocked:
        raise SystemExit("BLOCKED, nothing exported:\n" + json.dumps(blocked, ensure_ascii=False, indent=1))
    recs = [by[c] for c in ids]
    single = len(recs) == 1
    tpl_name = tpl_name or CFG["pillars"].get(recs[0].get("category"), "chaos")
    tpl = template(tpl_name)
    name = name or f"vci-{dt.datetime.now(dt.timezone.utc):%Y%m%d-%H%M%S}"
    work = OUT / name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    for f in (HERE / "fonts").glob("*.ttf"):
        shutil.copy(f, work / f.name)
    segs, speech, parts, t, hashes, langs = [], [], [], 0.0, [], []
    for i, rec in enumerate(recs):  # first id opens the countdown, last id is #1
        f = intelligence.media_for(rec, media)
        if not f:
            raise SystemExit(f"BLOCKED: source for {rec['content_id']} cannot be retrieved")
        start, end, a = segment(rec, f, single, revs[rec["content_id"]])
        peak = next((p for p in a["peaks_s"] if start <= p <= end), None)
        todo = [(start, end - start)]
        if single and "weak opening" in a["flags"] and peak:
            todo.insert(0, (max(0, peak - 0.3), 0.9))  # flash-forward over a weak opening
        first = t
        for st_, ln in todo:
            part = work / f"part{len(parts)}.mkv"
            cut(f.resolve(), st_, ln, peak, tpl, tpl["flash"] and bool(parts), part.resolve(),
                (a.get("window") or {}).get("brightness", 99) < 60)
            t += float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", part]).stdout)
            parts.append(part)
        cues, lang = french_speech(f, start, end)
        offset = t - (end - start)
        speech += [(round(a_ + offset, 2), round(min(b + offset, t), 2), x) for a_, b, x in cues]
        langs.append(lang)
        hashes.append(frame_hash(f, (start + end) / 2))
        segs.append({"content_id": rec["content_id"], "creator": rec["creator"], "platform": rec["platform"], "url": rec.get("url"),
                     "rights": rec["rights"], "start": round(start, 2), "end": round(end, 2), "at": round(first, 3),
                     "len": round(t - first, 3), "height": (a.get("source") or {}).get("height", 0), "dhash": hashes[-1],
                     "rank": None if single else len(recs) - i})
    total = round(t, 3)
    (work / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    base = work / "base.mkv"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", base.name], cwd=work)

    main = revs[ids[-1]]
    hook = revs[ids[0]]["hooks_fr"][0]
    if single:
        lines = [(0.15, hook.capitalize()), (2.6, main["action_fr"]), (total - 2.1, tpl["cta"])]
    else:
        lines = [(s["at"] + (0.15 if i == 0 else 0.35), f"Numéro {s['rank']}. {revs[s['content_id']]['hooks_fr'][0].capitalize()}")
                 for i, s in enumerate(segs)] + [(total - 2.1, tpl["cta"])]
    voices, subs, dropped, spoken, free = [], [], [], [], 0.0
    for i, (at, text) in enumerate(lines):
        at = max(at, free)
        limit = (lines[i + 1][0] if i + 1 < len(lines) else total) - at - 0.05
        if total - at < 0.6 or any(a_ < at + 1.0 and b > at for a_, b, _ in speech):
            dropped.append(text)
            continue
        wav = work / f"voice{i}.wav"
        d = speak(text, wav)
        tempo = 1.0
        if d:
            tempo = max(1.0, d / max(0.5, limit))
            if tempo > 1.3:  # too long for its slot: borrow time from the next line, or drop it
                limit = total - at - (2.2 if i + 1 < len(lines) else 0.05)
                tempo = max(1.0, d / max(0.5, limit))
                if tempo > 1.3:
                    dropped.append(text)
                    continue
            length = d / tempo
            voices.append((at, wav.name, tempo))
        else:
            length = min(limit, 0.5 + len(text) / 15)
        if length > 0.4:
            stop = min(total, at + length)
            subs += chunks(text, at, stop)
            spoken.append(text)
            free = stop + 0.05
    subs = sorted(subs + [s for s in speech if not any(a_ < s[1] and b > s[0] for a_, b, _ in subs)])
    ass_file(work / "brand.ass", tpl, hook, subs, segs, total)

    meta = {"id": name, "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "template": tpl_name,
            "badge": tpl["badge"], "format": "single" if single else f"top{len(recs)}",
            "category": recs[-1].get("category"), "duration_s": total, "sources": segs,
            "hook": hook, "alternative_hooks": revs[ids[0]]["hooks_fr"][1:],
            "narration": {"status": "generated" if voices else "skipped: no French voice available", "lines": spoken,
                          "dropped": dropped, "voice": os.environ.get("PIPER_VOICE"),
                          "voice_credit": os.environ.get("PIPER_CREDIT")},
            "subtitles": subs, "speech_languages": langs,
            "branding": {"logo": "VICECITY INTEL", "font": CFG["brand"]["font"], "accent": CFG["brand"][tpl["accent"]]},
            "duplicates": [] if test else duplicates(hashes, ids), "test": test, "exports": {}}
    cuts = [s["at"] for s in segs[1:]]
    credits = ", ".join(dict.fromkeys(s["creator"] for s in segs))
    title = f"{hook} 😱 GTA 6"
    credit_line = f"\nVoix : {os.environ['PIPER_CREDIT']}" if voices and os.environ.get("PIPER_CREDIT") else ""
    copy = {"youtube": {"title": f"{title} #Shorts"[:100],
                        "description": f"{main['action_fr']}\n{tpl['cta']} 👇\n🎥 Créateurs (Kick) : {credits}{credit_line}\n"
                                       "#GTA6 #GTAVI #GTA6FR #Shorts"},
            "tiktok": {"caption": f"{title} {tpl['cta']} 👇 🎥 {credits} (Kick) #GTA6 #GTA6FR #GTAVI #pourtoi"}}
    for platform in ("youtube", "tiktok"):
        mix, mmeta = music_for(tpl, platform, total)
        out = work / f"{name}_{platform}.mp4"
        export(work, base, total, voices, mix, cuts, tpl, out)
        checks = qc(out, {**meta, "music": mmeta})
        verdict = "fail" if any(c["result"] == "fail" for c in checks.values()) else \
            "warn" if any(c["result"] == "warn" for c in checks.values()) else "pass"
        meta["exports"][platform] = {"file": out.name, "music": mmeta, "copy": copy[platform], "qc": verdict, "checks": checks}
        run(["ffmpeg", "-v", "error", "-y", "-i", out, "-vf", "fps=1,scale=180:-2,tile=8x4", "-frames:v", "1",
             work / f"{name}_{platform}_sheet.jpg"])
    ok = all(e["qc"] != "fail" for e in meta["exports"].values())
    meta["status"] = "test_only" if test else "ready_for_approval" if ok else "failed_qc"
    meta["publishable"] = ok and not test
    meta["render_seconds"] = round((dt.datetime.now() - started).total_seconds())
    contentdb.write_json(work / "meta.json", meta)
    for p in [base, work / "list.txt", *parts, *work.glob("voice*.wav"), *work.glob("*.ttf")]:
        p.unlink(missing_ok=True)
    if meta["publishable"]:
        entry = {k: meta[k] for k in ("id", "created", "template", "format", "category", "duration_s", "hook", "sources", "status", "render_seconds")}
        entry["qc"] = {k: e["qc"] for k, e in meta["exports"].items()}
        entry["copy"] = copy
        entry["music"] = {k: e["music"] for k, e in meta["exports"].items()}
        contentdb.write_json(REG, registry() + [entry])
    return meta


def submit(meta):
    """Upload the exports, open the approval issue and add the queue entry. Nothing is published here."""
    import approvals
    if not meta.get("publishable"):
        raise SystemExit(f"{meta['id']} is not publishable ({meta['status']}); not submitted")
    repo = os.environ.get("GITHUB_REPOSITORY", "salahemd19/gta6-bot")
    work, base = OUT / meta["id"], f"https://github.com/{repo}/releases/download/clips/"
    yt, tt = meta["exports"]["youtube"], meta["exports"]["tiktok"]
    sheet = work / f"{meta['id']}_youtube_sheet.jpg"
    run(["gh", "release", "create", "clips", "--repo", repo, "--title", "Clips", "--notes", "Clips"], check=False)
    run(["gh", "release", "upload", "clips", work / yt["file"], work / tt["file"], sheet, "--repo", repo, "--clobber"])
    creators = ",".join(dict.fromkeys(s["creator"] for s in meta["sources"]))
    entry = {"id": meta["id"], "type": meta["format"], "created": meta["created"], "title": yt["copy"]["title"],
             "video_url": base + yt["file"], "video_url_tiktok": base + tt["file"], "sheet_url": base + sheet.name,
             "youtube_description": yt["copy"]["description"], "tiktok_caption": tt["copy"]["caption"],
             "tags": "GTA 6, GTA VI, GTA 6 FR, Vice City", "music": {p: e["music"] for p, e in meta["exports"].items()},
             "sources": meta["sources"], "streamer": creators, "rights": meta["sources"][0]["rights"],
             "authenticity": "verified_by_review", "category": meta["category"], "series": meta["badge"],
             "template": meta["template"], "hook": meta["hook"], "duration_s": meta["duration_s"], "score": 0,
             "render_seconds": meta["render_seconds"], "slot": meta["created"],
             "youtube": "awaiting approval", "tiktok": "awaiting approval"}
    body = (f"YouTube : {entry['video_url']}\nTikTok : {entry['video_url_tiktok']}\n\n![planche]({entry['sheet_url']})\n\n"
            f"Contrôle qualité : YouTube {yt['qc']}, TikTok {tt['qc']}\nMusique : YouTube {yt['music']['mode']} "
            f"({yt['music'].get('title')}), TikTok {tt['music']['mode']} ({tt['music'].get('title')})")
    approvals.ensure_labels()
    entry["issue"] = approvals.open_issue({**entry, "video_url": body})
    f = ROOT / "queue" / "manifest.json"
    contentdb.write_json(f, json.loads(f.read_text(encoding="utf-8")) + [entry])
    db = contentdb.load()
    ids = {s["content_id"] for s in meta["sources"]}
    for r in db.values():
        if r["content_id"] in ids:
            r["used_in"] = r["used_in"] + [meta["id"]]
            contentdb.set_fields(r, "factory", "produced", status="produced")
    contentdb.sync(db, "factory")
    contentdb.save(db)
    return entry


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["candidates", "produce", "check"])
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--template", choices=list(CFG["templates"]))
    ap.add_argument("--media")
    ap.add_argument("--id")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--submit", action="store_true", help="upload and open the approval issue")
    a = ap.parse_args()
    if a.cmd == "candidates":
        by, revs, used = index(contentdb.load()), intelligence.reviews(), used_sources()
        for cid, rv in revs.items():
            if rv.get("verdict") == "keep" and cid in by:
                why = blockers(by[cid], rv, used)
                print(cid, by[cid]["creator"], by[cid].get("category"), "READY" if not why else "; ".join(why))
    elif a.cmd == "check":
        meta = json.loads((Path(a.ids[0]) / "meta.json").read_text(encoding="utf-8"))
        for platform, e in meta["exports"].items():
            print(platform, json.dumps(qc(Path(a.ids[0]) / e["file"], {**meta, "music": e["music"]}), ensure_ascii=False, indent=1))
    else:
        meta = produce(a.ids, a.id, a.template, a.media, a.test)
        print(meta["id"], meta["status"], meta["duration_s"], "s", meta["narration"]["status"])
        for platform, e in meta["exports"].items():
            print(platform, e["qc"], e["music"]["mode"], {k: c["detail"] for k, c in e["checks"].items() if c["result"] != "pass"})
        if a.submit:
            print("approval issue", submit(meta)["issue"])


if __name__ == "__main__":
    main()
