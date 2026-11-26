"""VICECITY INTEL content intelligence (Phase 4): footage analysis -> transparent score -> French creative brief.

Every criterion says how it was obtained: "measured" (from pixels/audio), "heuristic" (a rule on measured or text
data), "review" (a human or Claude looked at the footage, db/reviews.json) or "not_assessed" (left out of the total,
never guessed). Weights are in config/scoring.json.

  python cloud/intelligence.py analyse [--limit 20] [--media DIR]   analyse and score candidates
  python cloud/intelligence.py rank [--limit 15]
  python cloud/intelligence.py brief VCI-xxxxxxxxxx
  python cloud/intelligence.py evaluate          compare scores with real accept/reject decisions
  python cloud/intelligence.py dashboard
"""
import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "music"))
import contentdb  # noqa: E402

CFG = json.loads((ROOT / "config" / "scoring.json").read_text(encoding="utf-8"))
WORK = ROOT / "work" / "engine" / "src"
HYPE = re.compile(r"\b(oh|wow|no+|non|what|wtf|omg|putain|regarde|attends|incroyable|dingue|mon dieu|oh my|let'?s go|"
                  r"que|nossa|caralho|joder|dios|kurwa|holy|bro|dude|jamais)\b", re.I)
_model = None


def clamp(x):
    return round(float(max(0.0, min(10.0, x))), 1)


# ------------------------------------------------------------------ footage analysis
def probe(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate:format=duration,bit_rate",
                        "-of", "json", str(f)], capture_output=True, text=True)
    j = json.loads(r.stdout or "{}")
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    num, den = (v.get("r_frame_rate") or "0/1").split("/")
    return {"width": v.get("width", 0), "height": v.get("height", 0), "fps": round(int(num) / max(1, int(den)), 1),
            "duration": round(float(j.get("format", {}).get("duration", 0)), 1),
            "kbps": int(float(j.get("format", {}).get("bit_rate", 0)) / 1000),
            "audio": any(s.get("codec_type") == "audio" for s in j.get("streams", []))}


def timeline(f, seconds=65):
    """Per quarter second: motion, brightness, sharpness (centre gameplay crop) and audio loudness."""
    w, h = 160, 90
    raw = subprocess.run(["ffmpeg", "-v", "error", "-t", str(seconds), "-i", str(f), "-vf", f"fps=4,scale={w}:{h},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    n = len(raw) // (w * h)
    if n < 8:
        raise ValueError("no readable video")
    fr = np.frombuffer(raw[: n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)
    mid = fr[:, :, w // 5: 4 * w // 5]
    motion = np.concatenate([[0], np.abs(np.diff(mid, axis=0)).mean(axis=(1, 2))])
    bright = mid.mean(axis=(1, 2))
    lap = (4 * mid[:, 1:-1, 1:-1] - mid[:, :-2, 1:-1] - mid[:, 2:, 1:-1] - mid[:, 1:-1, :-2] - mid[:, 1:-1, 2:])
    sharp = lap.var(axis=(1, 2))
    au = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-t", str(seconds), "-i", str(f), "-ac", "1", "-ar", "8000",
                                       "-f", "f32le", "-"], capture_output=True).stdout, np.float32)
    loud = np.array([np.sqrt((au[i * 2000: (i + 1) * 2000] ** 2).mean()) if (i + 1) * 2000 <= au.size else 0.0 for i in range(n)])
    return motion, bright, sharp, loud


def segments(mask, min_len=4):
    out, start = [], None
    for i, m in enumerate(list(mask) + [False]):
        if m and start is None:
            start = i
        elif not m and start is not None:
            if i - start >= min_len:
                out.append([start / 4, i / 4])
            start = None
    return out


def best_window(ex, dead):
    """Shortest strong cut: 6 to 22 s, opening just before an excitement rise and not on dead time."""
    n, best = len(ex), (0, min(len(ex), 26), -1e9)
    for L in (26, 40, 56, 72, 88):
        if L > n:
            continue
        for s in range(0, n - L + 1, 2):
            w = ex[s: s + L]
            val = w.mean() + 0.35 * ex[s: s + 4].mean() - 0.6 * dead[s: s + L].mean() - 0.002 * L
            if val > best[2]:
                best = (s, s + L, val)
    return best[0] / 4, best[1] / 4


def transcribe(f):
    """Speech in the clip, if faster-whisper is installed. Game dialogue and streamer voice are not separated."""
    global _model
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    if _model is None:
        try:
            try:
                _model = WhisperModel("base", compute_type="int8", local_files_only=True)
            except Exception:  # noqa: BLE001 - not cached yet
                _model = WhisperModel("base", compute_type="int8")
        except Exception as e:  # noqa: BLE001 - speech is optional: analyse without it and say so
            print("speech analysis unavailable:", str(e)[:100])
            _model = False
    if not _model:
        return None
    audio = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-t", "65", "-i", str(f), "-ac", "1", "-ar", "16000",
                                          "-f", "f32le", "-"], capture_output=True).stdout, np.float32)
    try:
        seg, info = _model.transcribe(audio, vad_filter=True)
        segs = [(s.start, s.end, s.text.strip()) for s in seg]
    except Exception as e:  # noqa: BLE001
        print("speech analysis failed:", str(e)[:100])
        return None
    return {"language": info.language, "text": " ".join(s[2] for s in segs)[:600],
            "segments": [[round(a, 1), round(b, 1), t] for a, b, t in segs][:30]}


def analyse_file(f, speech=True):
    info = probe(f)
    motion, bright, sharp, loud = timeline(f)
    mn = np.clip(motion / 30, 0, 1)
    ref = np.percentile(loud, 90) + 1e-6
    an = np.clip(loud / ref, 0, 1.5)
    burst = np.clip(loud - np.convolve(loud, np.ones(20) / 20, "same"), 0, None) / ref
    ex = 0.55 * mn + 0.25 * np.clip(an, 0, 1) + 0.6 * np.clip(burst, 0, 1)
    dead = ((motion < 4) & (loud < 0.35 * ref)) | (motion < 1.5) | (bright < 12)
    start, end = best_window(ex, dead.astype(float))
    i0, i1 = int(start * 4), int(end * 4)
    peaks = []
    for i in np.argsort(ex)[::-1]:
        if all(abs(i - p) > 16 for p in peaks):
            peaks.append(int(i))
        if len(peaks) == 4:
            break
    tr = transcribe(f) if speech and info["audio"] else None
    opening = {"motion": float(motion[i0 + 1: i0 + 5].mean()), "loud": float(an[i0: i0 + 4].mean()),
               "excitement": float(ex[i0: i0 + 4].mean())}
    flags = []
    if opening["excitement"] < 0.7 * ex[i0: i1].mean():
        flags.append("weak opening")
    if dead.mean() > 0.2:
        flags.append("dead time in source")
    if dead[:8].mean() > 0.5:
        flags.append("source starts slowly")
    if bright[i0: i1].mean() < 45:
        flags.append("very dark")
    if info["height"] < 720:
        flags.append("below 720p")
    return {"start": round(start, 2), "end": round(end, 2), "duration": round(end - start, 2), "source": info,
            "peaks_s": sorted(p / 4 for p in peaks), "sound_bursts_s": [s[0] for s in segments(burst > 0.45, 2)][:8],
            "scene_changes_s": [i / 4 for i in np.where(motion > max(35, motion.mean() * 3))[0][:10]],
            "dead_s": segments(dead), "flags": flags, "speech": tr,
            "window": {"motion": float(motion[i0:i1].mean()), "excitement": float(ex[i0:i1].mean()),
                       "variation": float(ex[i0:i1].std()), "burst": float(np.percentile(burst[i0:i1], 95)),
                       "brightness": float(bright[i0:i1].mean()), "sharpness": float(np.median(sharp[i0:i1])),
                       "dead_share": float(dead[i0:i1].mean()),
                       "build": float(ex[(i0 + i1) // 2: i1].max() - ex[i0: (i0 + i1) // 2].mean())},
            "opening": opening}


# ------------------------------------------------------------------ scoring
def score(rec, review=None):
    a, w, o = rec["analysis"], rec["analysis"]["window"], rec["analysis"]["opening"]
    s, how = {}, {}

    def put(k, v, m):
        s[k], how[k] = (None if v is None else clamp(v)), m

    tr = a.get("speech") or {}
    words = len(tr.get("text", "").split())
    hype = len(HYPE.findall(tr.get("text", "")))
    put("first_second", o["motion"] / 6 + 2 * min(o["loud"], 1) + 4 * o["excitement"] - 0.5, "measured")
    put("hook_potential", 6 * o["excitement"] + (1.5 if hype else 0) - (3 if "weak opening" in a["flags"] else 0), "heuristic")
    put("entertainment", 6 * w["excitement"] + 8 * w["variation"] - 6 * w["dead_share"], "heuristic")
    put("emotion", 5 * min(w["burst"], 1) + min(4, hype / 2) + (1 if a.get("speech") else 0), "heuristic")
    L = a["duration"]
    put("replayability", 10 - abs(L - 11) * 0.45 + (0.5 if a["scene_changes_s"] else 0), "heuristic")
    put("share_potential", 3 * w["excitement"] + 3 * min(w["burst"], 1) + min(2, math.log10(1 + rec.get("views", 0) / 100)) + 1, "heuristic")
    put("clarity", min(6, math.log10(1 + w["sharpness"]) * 2.4) + (4 if w["brightness"] > 60 else 2 if w["brightness"] > 40 else 0), "measured")
    fr = 5 + (4 if tr.get("language") == "fr" else 0) + (1.5 if words < 8 else 0) - (1 if words > 40 and tr.get("language") != "fr" else 0)
    put("french_relevance", fr, "heuristic")
    put("category", CFG["category_value"].get(rec.get("category") or "VIRAL MOMENTS & CHAOS", 6), "heuristic")
    i = a["source"]
    put("source_quality", (5 if i["height"] >= 1080 else 3.5 if i["height"] >= 720 else 1.5) + (2 if i["fps"] >= 50 else 1)
        + min(3, i["kbps"] / 2000), "measured")
    if review:
        put("originality", review.get("originality"), "review")
        put("storytelling", review.get("storytelling"), "review")
        for k in ("entertainment", "emotion", "hook_potential"):
            if review.get(k) is not None:
                put(k, review[k], "review")
    else:
        put("originality", None, "not_assessed")
        put("storytelling", None, "not_assessed")
    known = {k: v for k, v in s.items() if v is not None}
    wt = CFG["weights"]
    total = sum(known[k] * wt[k] for k in known) / sum(wt[k] for k in known)
    if review and review.get("verdict") == "reject":
        total = min(total, 3.0)
    return {**s, "total": round(total, 2), "method": how, "coverage": round(sum(wt[k] for k in known), 2),
            "model": CFG["version"], "reviewed": bool(review)}


# ------------------------------------------------------------------ French creative brief
HOOKS = {
    "VIRAL MOMENTS & CHAOS": ["IL N'AURAIT PAS DÛ FAIRE ÇA", "ÇA DÉRAPE EN QUELQUES SECONDES", "REGARDE JUSQU'À LA FIN", "LE CHAOS TOTAL À LEONIDA"],
    "RACING & VEHICLES": ["CE VÉHICULE EST INCONTRÔLABLE", "TIENS-TOI BIEN", "AURAIS-TU ÉVITÉ ÇA ?", "PIED AU PLANCHER À LEONIDA"],
    "MAP & SECRET DISCOVERIES": ["TU ES PASSÉ À CÔTÉ DE ÇA", "REGARDE BIEN CET ENDROIT", "QU'EST-CE QUE ÇA FAIT LÀ ?"],
    "CHALLENGES & EXPERIMENTS": ["EST-CE QUE ÇA PASSE ?", "IL TENTE L'IMPOSSIBLE", "FAIS TON PARI AVANT LA FIN"],
    "CHEATS, TIPS & MONEY": ["REGARDE CETTE TECHNIQUE", "TU FAISAIS SÛREMENT AUTREMENT", "À ESSAYER DANS TA PARTIE"],
    "LEONIDA LIFE & DETAILS": ["LE DÉTAIL QUE PERSONNE NE REGARDE", "LEONIDA EST VRAIMENT VIVANTE", "ARRÊTE-TOI SUR CETTE SCÈNE"],
}
CTAS = ["Tu aurais fait quoi ? Dis-le en commentaire", "Note ce moment sur 10", "Abonne-toi pour la suite du dossier",
        "Envoie ça à ton pote qui joue à GTA 6", "Tu l'avais déjà vu ? Réponds en commentaire"]


def pick(seq, key, k=1):
    h = int(hashlib.sha1(key.encode()).hexdigest(), 16)
    return [seq[(h + i) % len(seq)] for i in range(k)]


def treatment(rec):
    a = rec["analysis"]
    words = len((a.get("speech") or {}).get("text", "").split())
    if a["window"]["burst"] > 0.55 and words >= 6:
        return "REACTION"
    if a["window"]["motion"] > 18:
        return "ACTION_CUT"
    if rec.get("category") in ("MAP & SECRET DISCOVERIES", "LEONIDA LIFE & DETAILS", "CHEATS, TIPS & MONEY"):
        return "INVESTIGATION"
    return "SLOW_REVEAL"


STYLE = {
    "REACTION": ("Keep the original voice loud, one big French reaction caption on the peak, punch-in zoom on the burst.", "tension then comic release, music low", False),
    "ACTION_CUT": ("Cut on every impact, no intro, speed ramp into the first peak, rank or counter overlay.", "high-energy phonk or electronic, drop on the first impact", False),
    "INVESTIGATION": ("Freeze-frame and circle the detail, slow zoom, intelligence-file graphics in cyan.", "mysterious, atmospheric", True),
    "SLOW_REVEAL": ("Open on the most striking frame for 0.8 s, rewind, play to the payoff, hold the last frame.", "suspense building to a reveal", True),
}


def brief(rec, review=None):
    a, cat = rec["analysis"], rec.get("category") or "VIRAL MOMENTS & CHAOS"
    cat = cat if cat in HOOKS else "VIRAL MOMENTS & CHAOS"
    t = treatment(rec)
    edit, mood, narrate = STYLE[t]
    seen = (review or {}).get("action_fr")  # what actually happens, written by whoever watched it
    hooks = (review or {}).get("hooks_fr") or pick(HOOKS[cat], rec["content_id"], 3)
    hook, cta = hooks[0], pick(CTAS, rec["content_id"] + "cta")[0]
    s0 = a["start"]
    rel = [round(p - s0, 1) for p in a["peaks_s"] if s0 <= p <= a["end"]]
    desc = seen or "Un moment repéré en live sur GTA 6."
    steps = [f"Cut source {s0:.2f}s -> {a['end']:.2f}s ({a['duration']:.1f}s).", edit,
             f"Emphasise peaks at {', '.join(f'{p}s' for p in rel) or 'the middle'} of the cut.",
             "9:16, gameplay centre crop, creator credit on screen the whole time."]
    if "weak opening" in a["flags"] and rel:
        steps.insert(1, f"Weak opening: flash-forward 0.8 s from {rel[-1]}s before starting.")
    if "very dark" in a["flags"]:
        steps.append("Lift exposure and contrast.")
    try:
        import recommend
        cat_key = {"REACTION": "funny", "ACTION_CUT": "chaos", "INVESTIGATION": "secrets", "SLOW_REVEAL": "suspense"}[t]
        music = {p: [r["track"] for r in recommend.recommend(cat_key, p, a["duration"])] for p in ("youtube", "tiktok")}
    except Exception:  # noqa: BLE001
        music = {}
    script = None
    if narrate:
        script = f"[0 s] {hook.capitalize()}. [{max(2, round(a['duration'] / 2))} s] {desc} [fin] {cta} !"
    return {"treatment": t, "series": CFG["series"][cat], "category": cat, "hooks": hooks, "best_hook": hook,
            "title": f"{hook} 😱 GTA 6", "description": f"{desc} Créateur : @{rec['creator']} ({rec['platform'].title()}).",
            "caption": f"{hook} 😱 {cta} 👇 🎥 @{rec['creator']} #GTA6 #GTA6FR #GTAVI #pourtoi", "narration": script, "cta": cta,
            "editing": steps, "duration_s": a["duration"], "music_mood": mood, "music": music,
            "needs_review": None if seen else "Hooks are generic: nobody has described what happens yet. Check the footage before using."}


# ------------------------------------------------------------------ pipeline
def reviews():
    f = ROOT / "db" / "reviews.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def media_for(rec, folder):
    for d in [folder, WORK]:
        if d:
            f = Path(d) / f"{rec['id']}.mp4"
            if f.exists():
                return f
    if not rec.get("media_url"):
        return None
    WORK.mkdir(parents=True, exist_ok=True)
    f = WORK / f"{rec['id']}.mp4"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", rec["media_url"], "-t", "65", "-c", "copy", str(f)], timeout=240)
    return f if r.returncode == 0 and f.exists() else None


def process(rec, f, rv=None, speech=True, reuse=True):
    if not (reuse and rec.get("analysis")):
        rec["analysis"] = analyse_file(f, speech)
    rec["scores"] = score(rec, rv)
    rec["brief"] = brief(rec, rv) if rec["scores"]["total"] >= CFG["strong_candidate"] or rv else None


def auc(pos, neg):
    if not pos or not neg:
        return None
    return round(sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg)), 3)


def labelled(db):
    good = [r for r in db.values() if r["authenticity"] == "verified_by_review" and r.get("used_in")]
    bad = [r for r in db.values() if r.get("status") == "rejected_review" or r["authenticity"] == "not_gta6"]
    return good, bad


def dashboard(db):
    rows = []
    for r in sorted((r for r in db.values() if r.get("analysis") and r.get("scores", {}).get("model")),
                    key=lambda r: -r["scores"]["total"])[:150]:
        a = r["analysis"]
        rows.append({"id": r["content_id"], "creator": r["creator"], "url": r.get("url"), "title": r.get("description", ""),
                     "state": r["state"], "stage": r["stage"], "scores": r["scores"], "flags": a["flags"],
                     "cut": [a["start"], a["end"]], "peaks": a["peaks_s"], "speech": (a.get("speech") or {}).get("text", "")[:240],
                     "brief": r.get("brief")})
    ev = ROOT / "db" / "evaluation.json"
    data = {"generated": contentdb.now(), "weights": CFG["weights"], "rows": rows,
            "evaluation": json.loads(ev.read_text(encoding="utf-8")) if ev.exists() else None}
    tpl = (ROOT / "ops" / "evaluation_template.html").read_text(encoding="utf-8")
    (ROOT / "ops" / "evaluation_dashboard.html").write_text(
        tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")), encoding="utf-8")
    return len(rows)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["analyse", "rank", "brief", "evaluate", "dashboard"])
    ap.add_argument("key", nargs="?")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--media")
    ap.add_argument("--labelled", action="store_true", help="analyse the clips that already have an accept/reject decision")
    a = ap.parse_args()
    db, rv = contentdb.load(), reviews()
    if a.cmd == "analyse":
        if a.labelled:
            todo = [r for g in labelled(db) for r in g]
        else:  # reviewed first, then unscored by this model, best radar priority first
            todo = sorted((r for r in db.values() if (r["state"] == "active" and (r.get("scores") or {}).get("model") != CFG["version"])
                           or (r["content_id"] in rv)), key=lambda r: (r["content_id"] not in rv, -(r.get("radar") or {}).get("priority", 0)))
        done = 0
        for r in todo:
            if done >= a.limit:
                break
            try:
                f = media_for(r, a.media)
                if not f and not r.get("analysis"):
                    continue
                process(r, f, rv.get(r["content_id"]))
                done += 1
                print(r["content_id"], r["creator"], r["scores"]["total"], r["analysis"]["flags"], flush=True)
            except Exception as e:  # noqa: BLE001
                print(r["content_id"], "failed:", str(e)[:100])
        contentdb.sync(db, "intelligence")
        contentdb.save(db)
        print("analysed", done)
    elif a.cmd == "rank":
        for r in sorted((r for r in db.values() if r["state"] == "active" and r.get("scores", {}).get("model") and not r.get("used_in")),
                        key=lambda r: -r["scores"]["total"])[: a.limit]:
            print(contentdb.line(r), r["analysis"]["flags"])
    elif a.cmd == "brief":
        r = contentdb.resolve(db, a.key)
        print(json.dumps(r.get("brief") or brief(r, rv.get(r["content_id"])), indent=1, ensure_ascii=False))
    elif a.cmd == "evaluate":
        good, bad = labelled(db)
        # blind: scores recomputed without any review input, so decisions cannot leak into the score
        g = [score(r)["total"] for r in good if r.get("analysis")]
        b = [score(r)["total"] for r in bad if r.get("analysis")]
        crit = {k: auc([score(r)[k] for r in good if r.get("analysis")], [score(r)[k] for r in bad if r.get("analysis")])
                for k in CFG["weights"] if k not in ("originality", "storytelling")}
        res = {"model": CFG["version"], "accepted": len(g), "rejected": len(b), "auc_total": auc(g, b), "auc_by_criterion": crit,
               "mean_accepted": round(float(np.mean(g)), 2) if g else None, "mean_rejected": round(float(np.mean(b)), 2) if b else None,
               "at": contentdb.now(), "meaning": "AUC 0.5 = coin toss, 1.0 = perfect separation of accepted and rejected clips"}
        contentdb.write_json(ROOT / "db" / "evaluation.json", res)
        print(json.dumps(res, indent=1))
    else:
        print(dashboard(db), "rows")


if __name__ == "__main__":
    main()
