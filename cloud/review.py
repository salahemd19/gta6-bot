"""Footage review: the step between analysis and production. A reviewer (a Claude agent in the cloud or on the laptop,
or the owner) watches frame sheets and records keep or reject. Only kept footage can be produced, and the owner still
approves every video.

  python cloud/review.py queue [--n 12]     build frame sheets for the next clips (JSON on stdout)
  python cloud/review.py publish [--n 12]   build them and put them on the branch `review-queue` for the cloud reviewer
  python cloud/review.py apply FILE.json    check and record verdicts
  python cloud/review.py apply-remote       record the verdicts the cloud reviewer pushed to claude/review-verdicts

Verdict file: {"VCI-...": {"verdict": "reject", "reason": "...", "not_gta6": false},
               "VCI-...": {"verdict": "keep", "action_fr": "...", "hooks_fr": ["", "", ""], "category": "...",
                           "strength": 1-10, "window": [start_s, end_s]}}

A countdown shows only the first 6.5 s of the window: the key moment must fall inside them.
"""
import argparse
import datetime as dt
import json
import os
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
COLS, ROWS = 8, 2    # frames per clip
PER_SHEET = 2        # clips per image
CATEGORIES = list(factory.CFG["pillars"])
QUEUE_BRANCH = "review-queue"                 # written by the pipeline, replaced every time
VERDICT_BRANCH = "claude/review-verdicts"     # written by the cloud reviewer
VERDICT_FILE = "verdicts/latest.json"


def ready_count(db, revs):
    by, used = factory.index(db), factory.used_sources()
    return sum(1 for cid, rv in revs.items() if cid in by and rv.get("verdict") == "keep"
               and not factory.blockers(by[cid], rv, used))


def candidates(db, revs, n):
    """Newest first, one clip per creator per batch, analysed clips with a usable source. Streams marked mature are
    left out: their frames would sit on a public branch."""
    pool = [r for r in db.values() if r.get("status") == "analysed" and r.get("media_url") and not r.get("used_in")
            and r["content_id"] not in revs and r.get("state") == "active" and r.get("rights") in contentdb.PUBLISHABLE
            and not r.get("is_mature")]
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


def block(f, length, path):
    """Two rows of eight frames spread over the clip."""
    step = max(0.4, length / (COLS * ROWS))
    vf = (f"fps=1/{step:.3f},scale=240:136:force_original_aspect_ratio=decrease:force_divisible_by=2,"
          f"pad=240:136:(ow-iw)/2:(oh-ih)/2,tile={COLS}x{ROWS}:padding=3:color=magenta")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-t", f"{length:.2f}", "-i", str(f), "-vf", vf, "-frames:v", "1", str(path)])
    return r.returncode == 0 and path.exists()


def queue(n):
    db, revs = contentdb.load(), intelligence.reviews()
    ready = ready_count(db, revs)
    if ready >= ENOUGH:
        return {"ready": ready, "clips": [], "note": "enough approved footage; nothing to review"}
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.jpg"):
        old.unlink()
    blocks, clips = [], []
    for r in candidates(db, revs, n * 2):
        if len(clips) == n:
            break
        f = intelligence.media_for(r, None)
        if not f:
            continue
        length = min(float(r.get("duration") or 30), 60)
        path = OUT / f"block{len(clips):02d}.jpg"
        if not block(f, length, path):
            continue
        a = r.get("analysis")
        blocks.append(path)
        clips.append({"id": r["content_id"], "creator": r["creator"], "title": r.get("title"), "seconds": round(length, 1),
                      "seconds_per_frame": round(max(0.4, length / (COLS * ROWS)), 2),
                      "suggested_window": [a["start"], a["end"]] if a else None})
    sheets = []
    for k in range(0, len(blocks), PER_SHEET):
        group = blocks[k:k + PER_SHEET]
        sheet = OUT / f"sheet{k // PER_SHEET + 1}.jpg"
        if len(group) == 1:
            group[0].replace(sheet)
        else:
            ins = [x for p in group for x in ("-i", str(p))]
            subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex",
                            f"[0]pad=iw:ih+14:0:0:color=black[a];[a][1]vstack", "-frames:v", "1", str(sheet)], check=True)
        sheets.append(str(sheet))
        for i, c in enumerate(clips[k:k + PER_SHEET]):
            c["sheet"], c["position"] = sheet.name, "top" if i == 0 else "bottom"
    for p in OUT.glob("block*.jpg"):
        p.unlink()
    return {"ready": ready, "folder": str(OUT), "sheets": sheets, "clips": clips, "categories": CATEGORIES}


# ------------------------------------------------------------------ exchange with the cloud reviewer
def git(*args, text_in=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "vci-pipeline", "GIT_COMMITTER_NAME": "vci-pipeline",
           "GIT_AUTHOR_EMAIL": "vci-pipeline@users.noreply.github.com",
           "GIT_COMMITTER_EMAIL": "vci-pipeline@users.noreply.github.com"}
    return subprocess.run(["git", *args], cwd=ROOT, input=text_in, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)


def must(*args, **kw):
    r = git(*args, **kw)
    if r.returncode:
        raise RuntimeError(f"git {args[0]} failed: {r.stderr[-300:]}")
    return r.stdout.strip()


def publish(n):
    """Replace the review-queue branch with one commit holding the sheets and their list. The working tree is untouched."""
    q = queue(n)
    if not q["clips"]:
        return q.get("note", "no clip waiting for review")
    folder = Path(q.pop("folder"))
    q["queue_id"] = dt.datetime.now(dt.timezone.utc).strftime("q%Y%m%d-%H%M%S")
    q["sheets"] = [Path(s).name for s in q["sheets"]]
    (folder / "queue.json").write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
    tree = "".join(f"100644 blob {must('hash-object', '-w', str(folder / name))}\t{name}\n"
                   for name in sorted(q["sheets"] + ["queue.json"]))
    commit = must("commit-tree", must("mktree", text_in=tree), "-m", f"review queue {q['queue_id']}")
    must("push", "-f", "origin", f"{commit}:refs/heads/{QUEUE_BRANCH}")
    return f"published {len(q['clips'])} clips as {q['queue_id']}"


def apply_remote():
    """Record the cloud reviewer's verdicts for clips that are still waiting. The file is data: every entry is checked."""
    if git("fetch", "-q", "origin", VERDICT_BRANCH).returncode:
        return "no verdicts from the cloud reviewer yet"
    shown = git("show", f"FETCH_HEAD:{VERDICT_FILE}")
    if shown.returncode:
        return "the verdict branch has no verdict file"
    data = json.loads(shown.stdout.lstrip("﻿"))
    if not isinstance(data, dict):
        raise RuntimeError("verdict file is not an object")
    db, revs = contentdb.load(), intelligence.reviews()
    by = factory.index(db)
    new = {k: v for k, v in data.items() if k not in revs and (by.get(k) or {}).get("status") == "analysed"}
    if not new:
        return "no new verdict"
    done, bad = apply(new, "Cloud Claude review")
    for cid, why in list(bad.items())[:5]:
        print("refused", cid, why)
    return f"{len(done)} verdicts recorded, {len(bad)} refused"


# ------------------------------------------------------------------ verdicts
def problems(cid, v, rec):
    if not isinstance(v, dict):
        return "verdict must be an object"
    if rec is None:
        return "unknown content id"
    if v.get("verdict") == "reject":
        return None if isinstance(v.get("reason"), str) and 0 < len(v["reason"]) <= 200 else "a rejection needs a short reason"
    if v.get("verdict") != "keep":
        return "verdict must be keep or reject"
    if rec.get("state") != "active" or rec.get("used_in"):
        return "clip is not available (rejected, expired or already used)"
    action = v.get("action_fr")
    if not isinstance(action, str) or not 0 < len(action.strip()) <= 220:
        return "action_fr is missing or too long"
    hooks = v.get("hooks_fr")
    if not isinstance(hooks, list) or len(hooks) != 3 or not all(isinstance(h, str) and 0 < len(h) <= 48 for h in hooks):
        return "hooks_fr needs 3 short French hooks (48 characters at most)"
    if v.get("category") not in CATEGORIES:
        return "category must be one of the six pillars"
    if not isinstance(v.get("strength"), (int, float)) or not 1 <= v["strength"] <= 10:
        return "strength must be 1 to 10"
    w = v.get("window")
    length = min(float(rec.get("duration") or 0), 65)
    if not (isinstance(w, list) and len(w) == 2 and all(isinstance(x, (int, float)) for x in w)
            and 0 <= w[0] < w[1] <= length + 0.5 and w[1] - w[0] >= 4):
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
    ap.add_argument("cmd", choices=["queue", "publish", "apply", "apply-remote"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--n", type=int, default=12)
    a = ap.parse_args()
    if a.cmd == "queue":
        print(json.dumps(queue(a.n), ensure_ascii=False, indent=1))
    elif a.cmd == "publish":
        print(publish(a.n))
    elif a.cmd == "apply-remote":
        print(apply_remote())
    else:
        done, bad = apply(json.loads(Path(a.file).read_text(encoding="utf-8-sig")))
        print(f"recorded {len(done)}; ready for production: {ready_count(contentdb.load(), intelligence.reviews())}")
        if bad:
            raise SystemExit("refused:\n" + json.dumps(bad, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
