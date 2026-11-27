"""Git merge driver for the shared data files, so cloud jobs and the laptop never overwrite each other.

Called by git as: mergedb.py BASE OURS THEIRS PATH  (result is written to OURS). During a rebase OURS is what is
already on the server and THEIRS is the commit being replayed.

JSON: field by field; lists of records are matched by id. If both sides changed the same field, the newer commit
wins, except publishing statuses, which never move backwards. JSON-lines: union. Generated pages: newer one.
"""
import json
import sys
from pathlib import Path

RANK = ["awaiting", "pending", "failed", "hold", "scheduled", "rejected", "retired", "deleted", "posted"]
MISSING = object()


def rank(v):
    return next((i for i, p in enumerate(RANK) if str(v).startswith(p)), -1)


def keyed(v):
    return isinstance(v, list) and v and all(isinstance(x, dict) and "id" in x for x in v)


def merge(base, ours, theirs, key=None):
    if ours == theirs:
        return ours
    if ours == base:
        return theirs
    if theirs == base:
        return ours
    if isinstance(ours, dict) and isinstance(theirs, dict):
        b = base if isinstance(base, dict) else {}
        out = {}
        for k in list(ours) + [k for k in theirs if k not in ours]:
            v = merge(b.get(k, MISSING), ours.get(k, MISSING), theirs.get(k, MISSING), k)
            if v is not MISSING:
                out[k] = v
        return out
    if keyed(ours) and keyed(theirs):
        index = lambda v: {x["id"]: x for x in v} if keyed(v) else {}
        merged = merge(index(base), index(ours), index(theirs))
        return list(merged.values())
    if isinstance(ours, list) and isinstance(theirs, list):
        old = base if isinstance(base, list) else []
        gone = [x for x in old if x not in ours or x not in theirs]
        return [x for x in ours if x not in gone] + [x for x in theirs if x not in ours and x not in gone]
    if key in ("youtube", "tiktok") and isinstance(ours, str) and isinstance(theirs, str) and rank(ours) != rank(theirs):
        return ours if rank(ours) > rank(theirs) else theirs
    return theirs if theirs is not MISSING else ours


def merge_text(base, ours, theirs, path):
    if path.endswith(".jsonl"):
        a = ours.splitlines()
        seen = set(a)
        return "\n".join(a + [x for x in theirs.splitlines() if x not in seen]) + "\n"
    if path.endswith(".json"):
        load = lambda s: json.loads(s) if s.strip() else None
        return json.dumps(merge(load(base), load(ours), load(theirs)), indent=1, ensure_ascii=False)
    return theirs


def main():
    base, ours, theirs, path = sys.argv[1:5]
    read = lambda f: Path(f).read_text(encoding="utf-8-sig")
    Path(ours).write_text(merge_text(read(base), read(ours), read(theirs), path), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
