"""Footage review: the step between analysis and production. A reviewer (Claude on the laptop, or the owner) watches
frame sheets and records keep or reject. Only kept footage can be produced, and the owner still approves every video.

  python cloud/review.py queue [--n 12]     build frame sheets for the next clips (JSON list on stdout)
  python cloud/review.py apply FILE.json    check and record the verdicts

Verdict file: {"VCI-...": {"verdict": "reject", "reason": "...", "not_gta6": false},
               "VCI-...": {"verdict": "keep", "action_fr": "...", "hooks_fr": ["", "", ""], "category": "...",
                           "strength": 1-10, "window": [start_s, end_s]}}
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import contentdb  # noqa: E402
import factory  # noqa: E402
import intelligence  # noqa: E402

OUT = ROOT / "work" / "review"
REVIEWS = ROOT / "db" / "reviews.json"
ENOUGH = 18          # approved clips waiting for production; above this no new review is needed
FRAMES = 8           # frames per clip
PER_SHEET = 4        # clips per image
CATEGORIES = list(factory.CFG["pillars"])


def ready_count(db, revs):
    by, used = factory.index(db), factory.used_sources()
    return sum(1 for cid, rv in revs.items() if cid in by and rv.get("verdict") == "keep"
               and not factory.blockers(by[cid], rv, used))


def candidates(db, revs, n):
    """Newest first, one clip per creator per batch, analysed clips with a usable source."""
    pool = [r for r in db.values() if r.get("status") == "analysed" and r.get("media_url") and not r.get("used_in")
            and r["content_id"] not in revs and r.get("state") == "active" and r.get("rights") in contentdb.PUBLISHABLE]
    recent = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).isoformat()
    pool.sort(key=lambda r: (str(r.get("discovered_at", "")) >= recent, (r.get("scores") or {}).get("total", 0)), reverse=True)
    out, creators = [], set()
    for r in pool:
        if r["creator"] not in creators:
            out.append(r)
            creators.add(r["creator"])
        if len(out) == n:
            break
    return out


def strip(f, start, end, row):
    """One horizontal strip of frames across the suggested window."""
    step = max(0.5, (end - start) / FRAMES)
    vf = (f"fps=1/{step:.3f},scale=240:136:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=240:136:(ow-iw)/2:(oh-ih)/2,"
          f"tile={FRAMES}x1:padding=3:color=magenta")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}", "-i", str(f), "-vf", vf,
                        "-frames:v", "1", str(row)])
    return r.returncode == 0 and row.exists()


def queue(n):
    db, revs = contentdb.load(), intelligence.reviews()
    ready = ready_count(db, revs)
    if ready >= ENOUGH:
        return {"ready": ready, "clips": [], "note": "enough approved footage; nothing to review"}
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.jpg"):
        old.unlink()
    rows, clips = [], []
    for r in candidates(db, revs, n * 2):
        if len(clips) == n:
            break
        f = intelligence.media_for(r, None)
        a = r.get("analysis")
        if not f:
            continue
        length = min(float(r.get("duration") or 30), 60)
        start, end = 0.0, length
        row = OUT / f"row{len(clips):02d}.jpg"
        if not strip(f, start, end, row):
            continue
        rows.append(row)
        clips.append({"id": r["content_id"], "creator": r["creator"], "title": r.get("title"), "seconds": round(length, 1),
                      "seconds_per_frame": round(max(0.5, length / FRAMES), 2),
                      "suggested_window": [a["start"], a["end"]] if a else None})
    sheets = []
    for k in range(0, len(rows), PER_SHEET):
        group = rows[k:k + PER_SHEET]
        sheet = OUT / f"sheet{k // PER_SHEET + 1}.jpg"
        if len(group) == 1:
            group[0].replace(sheet)
        else:
            ins = [x for p in group for x in ("-i", str(p))]
            subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex",
                            f"vstack=inputs={len(group)}", "-frames:v", "1", str(sheet)], check=True)
        sheets.append(str(sheet))
        for i, c in enumerate(clips[k:k + PER_SHEET]):
            c["sheet"], c["row"] = sheet.name, i + 1
    for p in OUT.glob("row*.jpg"):
        p.unlink()
    return {"ready": ready, "folder": str(OUT), "sheets": sheets, "clips": clips, "categories": CATEGORIES}


def problems(cid, v, rec):
    if rec is None:
        return "unknown content id"
    if v.get("verdict") == "reject":
        return None if v.get("reason") else "a rejection needs a reason"
    if v.get("verdict") != "keep":
        return "verdict must be keep or reject"
    if rec.get("state") != "active" or rec.get("used_in"):
        return "clip is not available (rejected, expired or already used)"
    if not str(v.get("action_fr", "")).strip():
        return "action_fr is missing"
    hooks = v.get("hooks_fr")
    if not isinstance(hooks, list) or len(hooks) != 3 or not all(isinstance(h, str) and 0 < len(h) <= 48 for h in hooks):
        return "hooks_fr needs 3 short French hooks (48 characters at most)"
    if v.get("category") not in CATEGORIES:
        return "category must be one of the six pillars"
    if not isinstance(v.get("strength"), (int, float)) or not 1 <= v["strength"] <= 10:
        return "strength must be 1 to 10"
    w = v.get("window")
    length = min(float(rec.get("duration") or 0), 65)
    if not (isinstance(w, list) and len(w) == 2 and 0 <= w[0] < w[1] <= length + 0.5 and w[1] - w[0] >= 4):
        return f"window must be [start, end] inside 0-{length:.0f} s and at least 4 s long"
    return None


def apply(verdicts, by_whom="Claude frame-sheet review", db=None, revs=None):
    """Record valid verdicts; return (accepted ids, {id: problem})."""
    own = db is None
    db = contentdb.load() if own else db
    revs = intelligence.reviews() if own else revs
    by = factory.index(db)
    today = dt.date.today().isoformat()
    done, bad = [], {}
    for cid, v in verdicts.items():
        rec = by.get(cid)
        why = problems(cid, v, rec)
        if why:
            bad[cid] = why
            continue
        revs[cid] = {**v, "by": f"{by_whom} {today}"}
        if v["verdict"] == "reject":
            contentdb.set_fields(rec, "review", v["reason"], status="rejected_review", state="rejected", manual_state=True,
                                 authenticity="not_gta6" if v.get("not_gta6") else rec.get("authenticity"))
        else:
            rec["category"], rec["category_reviewed"] = v["category"], True
            contentdb.set_fields(rec, "review", "kept after frame review", authenticity="verified_by_review",
                                 authenticity_evidence=rec.get("authenticity_evidence", []) + [f"Frame sheet reviewed {today}"])
            f = intelligence.media_for(rec, None) if own else None
            if f or rec.get("analysis"):
                intelligence.process(rec, f, revs[cid])
        done.append(cid)
    if own:
        contentdb.write_json(REVIEWS, revs)
        contentdb.sync(db, "review")
        contentdb.save(db)
    return done, bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["queue", "apply"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--n", type=int, default=12)
    a = ap.parse_args()
    if a.cmd == "queue":
        print(json.dumps(queue(a.n), ensure_ascii=False, indent=1))
    else:
        done, bad = apply(json.loads(Path(a.file).read_text(encoding="utf-8-sig")))
        by = factory.index(contentdb.load())
        print(f"recorded {len(done)}; ready for production: {ready_count(contentdb.load(), intelligence.reviews())}")
        if bad:
            raise SystemExit("refused:\n" + json.dumps(bad, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
