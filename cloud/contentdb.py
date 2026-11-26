"""VICECITY INTEL central content database (Phase 3).

One store: db/clips.json (one record per candidate), db/history.jsonl (append-only change log).
This module owns the data model, the lifecycle, the publication gate, search, bulk edits and backups.

  python cloud/contentdb.py stats
  python cloud/contentdb.py search --stage SCORED --creator xqc --min-score 6 --category RACING
  python cloud/contentdb.py show VCI-1a2b3c4d5e
  python cloud/contentdb.py history VCI-1a2b3c4d5e
  python cloud/contentdb.py advance VCI-... EDITORIAL_REVIEW --note "..."
  python cloud/contentdb.py bulk --stage DISCOVERED --creator spammer --state rejected --note "repost" [--apply]
  python cloud/contentdb.py edit VCI-... --notes "..." --hook "..." --subcategory chase --rights licensed --evidence "..."
  python cloud/contentdb.py metrics VCI-... youtube views=1200 likes=40
  python cloud/contentdb.py validate | sync | backup | restore <file.zip> --into <dir>
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(os.environ.get("VCI_ROOT") or Path(__file__).resolve().parent.parent)

STAGES = ["DISCOVERED", "AUTHENTICITY_REVIEW", "ANALYSED", "SCORED", "RIGHTS_RECORDED", "EDITORIAL_REVIEW",
          "APPROVED_FOR_PRODUCTION", "PRODUCED", "APPROVED_FOR_PUBLICATION", "SCHEDULED", "PUBLISHED",
          "PERFORMANCE_ANALYSED"]
STATES = ["active", "rejected", "duplicated", "expired", "rights_unverified"]
AUTH = ["unchecked", "category_only", "verified_by_review", "not_gta6"]
RIGHTS = ["owned", "licensed", "permission_granted", "credited_third_party", "unverified", "unresolved", "refused"]
# The owner's standing policy (26 Nov 2026) lets credited third-party clips be published. Remove it from this set
# to enforce "verified rights only"; bot/post_next.py has the matching list.
PUBLISHABLE = {"owned", "licensed", "permission_granted", "credited_third_party"}
EXPIRE_DAYS = 7


class DBError(Exception):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def path(*p):
    return ROOT.joinpath(*p)


def read_json(f, default):
    if not f.exists():
        return default
    try:
        return json.loads(f.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:  # never continue (and overwrite) on a damaged file
        raise DBError(f"{f} is damaged ({e}). Restore it with git or 'contentdb.py restore'.") from e


def write_json(f, obj):
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(f.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, f)  # atomic: a crash never leaves a half-written database


def load():
    return read_json(path("db", "clips.json"), {})


def save(db):
    write_json(path("db", "clips.json"), db)


def log_change(rec, changes, actor, note=""):
    if not changes:
        return
    f = path("db", "history.jsonl")
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as h:
        h.write(json.dumps({"at": now(), "id": rec["content_id"], "by": actor, "changes": changes, "note": note},
                           ensure_ascii=False) + "\n")


def set_fields(rec, actor, note="", **fields):
    changes = {k: [rec.get(k), v] for k, v in fields.items() if rec.get(k) != v}
    for k, (_, v) in changes.items():
        rec[k] = v
    if changes:
        rec["updated_at"] = now()
    log_change(rec, changes, actor, note)
    return bool(changes)


# ------------------------------------------------------------------ model
def content_id(source, key):
    return "VCI-" + hashlib.sha1(f"{source}:{key}".encode()).hexdigest()[:10]


def norm_url(u):
    return (u or "").split("?")[0].split("#")[0].rstrip("/").lower().replace("https://www.", "https://")


def hook_for(rec):
    hooks = {"RACING & VEHICLES": "CETTE VOITURE N'AURAIT JAMAIS DÛ FAIRE ÇA",
             "MAP & SECRET DISCOVERIES": "PERSONNE N'A VU CE SECRET SUR GTA 6",
             "CHALLENGES & EXPERIMENTS": "IL A TENTÉ L'IMPOSSIBLE SUR GTA 6",
             "CHEATS, TIPS & MONEY": "REGARDE BIEN CETTE TECHNIQUE",
             "LEONIDA LIFE & DETAILS": "CE DÉTAIL DE LEONIDA EST FOU",
             "VIRAL MOMENTS & CHAOS": "ILS ONT FAIT ÇA SUR GTA 6"}
    return hooks.get(rec.get("category"), hooks["VIRAL MOMENTS & CHAOS"])


def ensure_model(rec):
    """Fill every required field without overwriting what is already recorded."""
    d = rec.setdefault
    d("content_id", content_id(rec.get("source", "?"), rec.get("id") or rec.get("url")))
    d("creator", "?")
    d("platform", rec.get("source", "?"))
    d("account_url", f"https://kick.com/{rec['creator']}" if rec["platform"] == "kick" else "")
    d("url", "")
    d("clip_url", rec.get("media_url", ""))
    d("created_at", None)
    d("discovered_at", now())
    d("authenticity", "category_only" if rec["platform"] == "kick" else "unchecked")
    if rec["authenticity"] == "unchecked" and rec["platform"] == "kick":
        rec["authenticity"] = "category_only"
    d("authenticity_evidence", ["Listed in Kick's Grand Theft Auto VI category (not proof by itself)"]
      if rec["platform"] == "kick" else [])
    d("category", rec.get("pillar") or "")
    if rec.get("pillar"):
        rec["category"] = rec["pillar"]
    d("subcategory", ", ".join((rec.get("radar") or {}).get("topics", [])))
    d("description", rec.get("title", ""))
    d("editorial_notes", "")
    d("rights", "unverified")
    d("licence", "")
    d("rights_basis", "Owner policy 26 Nov 2026: published with credit, removed on request; no permission obtained"
      if rec["rights"] == "credited_third_party" else "")
    d("attribution", f"@{rec['creator']} ({rec['platform'].title()})")
    d("duplicate_of", None)
    d("used_in", [])
    d("suggested_hook", "")
    d("suggested_title", "")
    d("production_status", "none")
    d("approval", {"editorial": None, "production": None, "publication": None})
    d("publications", [])
    d("analytics", {})
    d("stage", "DISCOVERED")
    d("state", "active")
    d("updated_at", rec["discovered_at"])
    return rec


def score_total(rec):
    return (rec.get("scores") or {}).get("total", 0)


# ------------------------------------------------------------------ lifecycle
def blockers(rec, target):
    """Why a record cannot move to `target` ([] = allowed)."""
    out = []
    i = STAGES.index(target)
    if rec["state"] in ("rejected", "duplicated", "expired"):
        out.append(f"state is {rec['state']}")
    if i >= STAGES.index("SCORED") and not rec.get("scores"):
        out.append("no score")
    if i >= STAGES.index("APPROVED_FOR_PRODUCTION") and rec["authenticity"] != "verified_by_review":
        out.append("GTA 6 authenticity not verified by review")
    if i >= STAGES.index("APPROVED_FOR_PUBLICATION"):
        if rec["rights"] not in PUBLISHABLE:
            out.append(f"rights '{rec['rights']}' are not publishable")
        if not rec.get("attribution"):
            out.append("no attribution")
    if i >= STAGES.index("PUBLISHED") and not rec.get("publications"):
        out.append("no publication recorded")
    return out


def advance(rec, target, actor, note=""):
    if target not in STAGES:
        raise DBError(f"unknown stage {target}")
    cur, new = STAGES.index(rec["stage"]), STAGES.index(target)
    if new != cur + 1:
        raise DBError(f"{rec['content_id']}: cannot jump {rec['stage']} -> {target}; next is "
                      f"{STAGES[cur + 1] if cur + 1 < len(STAGES) else 'none'}")
    why = blockers(rec, target)
    if why:
        raise DBError(f"{rec['content_id']}: blocked from {target}: {'; '.join(why)}")
    set_fields(rec, actor, note, stage=target)


def publication_queue(db):
    """The only records allowed into the final publication queue."""
    return [r for r in db.values() if r.get("stage") == "APPROVED_FOR_PUBLICATION" and r.get("state") == "active"
            and not blockers(r, "APPROVED_FOR_PUBLICATION")]


def derive(rec):
    """Furthest stage supported by evidence already in the record (pipeline results, never assumptions)."""
    st = str(rec.get("status", "discovered"))
    pubs = rec.get("publications") or []
    state = "active"
    if st == "rejected_duplicate" or rec.get("duplicate_of"):
        state = "duplicated"
    elif st.startswith("rejected") or rec.get("authenticity") == "not_gta6" or rec.get("rights") == "refused":
        state = "rejected"
    elif rec.get("rights") not in PUBLISHABLE:
        state = "rights_unverified"
    elif st in ("discovered", "error") and rec.get("created_at"):
        try:
            t = dt.datetime.fromisoformat(rec["created_at"].replace("Z", "+00:00"))
            if (dt.datetime.now(dt.timezone.utc) - t).days >= EXPIRE_DAYS:
                state = "expired"
        except ValueError:
            pass
    stage = "DISCOVERED"
    if rec.get("metrics"):
        stage = "ANALYSED"
    if rec.get("scores"):
        stage = "RIGHTS_RECORDED" if rec.get("rights") else "SCORED"
    if rec.get("used_in"):
        stage = "PRODUCED"
    if any(p["status"] == "scheduled" for p in pubs):
        stage = "SCHEDULED"
    if any(p["status"] == "published" for p in pubs):
        stage = "PUBLISHED"
    if rec.get("analytics"):
        stage = "PERFORMANCE_ANALYSED"
    return stage, state


def find_duplicates(db):
    seen, dups = {}, []
    for k, r in sorted(db.items(), key=lambda kv: kv[1].get("discovered_at") or ""):
        for key in (norm_url(r.get("url")), norm_url(r.get("clip_url"))):
            if key and key in seen and seen[key] != k:
                dups.append((k, seen[key]))
                break
            if key:
                seen[key] = k
    return dups


def add(db, rec, actor="manual"):
    """Insert a candidate; refuses duplicates by source key or URL. Returns (record, created)."""
    ensure_model(rec)
    for r in db.values():
        if r.get("content_id") == rec["content_id"] or (norm_url(rec["url"]) and norm_url(r.get("url")) == norm_url(rec["url"])):
            return r, False
    key = rec.get("id") or rec["content_id"]
    rec.setdefault("id", key)
    rec.setdefault("status", "discovered")
    db[key] = rec
    log_change(rec, {"created": [None, rec["url"]]}, actor)
    return rec, True


def sync(db, actor="pipeline"):
    """Bring every record up to date from pipeline results. Safe to run any number of times."""
    changed = 0
    for rec in db.values():
        new = "content_id" not in rec
        ensure_model(rec)
        if new:
            log_change(rec, {"created": [None, rec["url"]]}, actor)
        stage, state = derive(rec)
        up = {}
        if STAGES.index(stage) > STAGES.index(rec["stage"]):  # pipeline evidence only moves a record forward
            up["stage"] = stage
        if rec["state"] != state and not rec.get("manual_state"):
            up["state"] = state
        if rec.get("scores"):
            up["viral_potential"] = rec["scores"]["total"]
            if not rec.get("suggested_hook"):
                up["suggested_hook"] = hook_for(rec)
                up["suggested_title"] = f"{hook_for(rec).capitalize()} 😱 (@{rec['creator']})"
        prod = "published" if stage in ("PUBLISHED", "PERFORMANCE_ANALYSED") else "produced" if rec.get("used_in") else "none"
        up["production_status"] = prod
        changed += set_fields(rec, actor, "sync", **up)
    for k, orig in find_duplicates(db):
        changed += set_fields(db[k], actor, "same URL", duplicate_of=orig, state="duplicated")
    return changed


# ------------------------------------------------------------------ search, bulk, backup
def search(db, creator=None, category=None, platform=None, stage=None, state=None, min_score=None, rights=None, text=None):
    out = []
    for r in db.values():
        if creator and creator.lower() not in r.get("creator", "").lower():
            continue
        if category and category.lower() not in (r.get("category", "") + " " + r.get("subcategory", "")).lower():
            continue
        if platform and platform != r.get("platform"):
            continue
        if stage and stage != r.get("stage"):
            continue
        if state and state != r.get("state"):
            continue
        if rights and rights != r.get("rights"):
            continue
        if min_score is not None and score_total(r) < min_score:
            continue
        if text and text.lower() not in (r.get("description", "") + " " + r.get("editorial_notes", "")).lower():
            continue
        out.append(r)
    return sorted(out, key=lambda r: (-score_total(r), -(r.get("views") or 0)))


def validate(db):
    problems = []
    ids = {}
    for k, r in db.items():
        for f in ("content_id", "creator", "platform", "url", "discovered_at", "stage", "state", "rights", "authenticity"):
            if r.get(f) in (None, ""):
                problems.append(f"{k}: missing {f}")
        if r.get("stage") not in STAGES:
            problems.append(f"{k}: bad stage {r.get('stage')}")
        if r.get("state") not in STATES:
            problems.append(f"{k}: bad state {r.get('state')}")
        if r.get("rights") not in RIGHTS:
            problems.append(f"{k}: bad rights {r.get('rights')}")
        if r.get("authenticity") not in AUTH:
            problems.append(f"{k}: bad authenticity {r.get('authenticity')}")
        if r.get("content_id") in ids:
            problems.append(f"{k}: content_id also used by {ids[r['content_id']]}")
        ids[r.get("content_id")] = k
    return problems


def backup(dest=None):
    dest = Path(dest or path("work", f"backup-{dt.datetime.now(dt.timezone.utc):%Y%m%d-%H%M}.zip"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    files = [f for d in ("db", "queue", "config") for f in path(d).glob("*") if f.suffix in (".json", ".jsonl")]
    files += [f for f in [path("music", "library.json"), path("music", "usage_log.json")] if f.exists()]
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        manifest = {}
        for f in files:
            name = f.relative_to(ROOT).as_posix()
            data = f.read_bytes()
            manifest[name] = hashlib.sha256(data).hexdigest()
            z.writestr(name, data)
        z.writestr("MANIFEST.json", json.dumps(manifest, indent=1))
    return dest


def restore(zip_path, into):
    """Extract into a chosen folder after checking every checksum. Never overwrites the live database by itself."""
    into = Path(into)
    with zipfile.ZipFile(zip_path) as z:
        manifest = json.loads(z.read("MANIFEST.json"))
        for name, digest in manifest.items():
            if ".." in name or name.startswith("/"):
                raise DBError(f"unsafe path in backup: {name}")
            data = z.read(name)
            if hashlib.sha256(data).hexdigest() != digest:
                raise DBError(f"checksum mismatch: {name}")
            (into / name).parent.mkdir(parents=True, exist_ok=True)
            (into / name).write_bytes(data)
    return len(manifest)


def resolve(db, key):
    for k, r in db.items():
        if key in (k, r.get("content_id")):
            return r
    raise DBError(f"not found: {key}")


def line(r):
    return (f"{r['content_id']}  {score_total(r):>5}  {r['stage']:<24} {r['state']:<17} {r['creator'][:18]:<18} "
            f"{(r.get('description') or '')[:45]}")


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("stats", "validate", "sync"):
        sub.add_parser(c)
    for c in ("search", "bulk"):
        p = sub.add_parser(c)
        for f in ("creator", "category", "platform", "stage", "rights", "text"):
            p.add_argument("--" + f)
        p.add_argument("--min-score", type=float)
        p.add_argument("--in-state")
        if c == "bulk":
            p.add_argument("--state", choices=STATES, required=True)
            p.add_argument("--note", required=True)
            p.add_argument("--apply", action="store_true")
        else:
            p.add_argument("--limit", type=int, default=25)
    for c in ("show", "history"):
        sub.add_parser(c).add_argument("key")
    p = sub.add_parser("advance"); p.add_argument("key"); p.add_argument("stage"); p.add_argument("--note", default="")
    p = sub.add_parser("edit"); p.add_argument("key")
    for f in ("notes", "hook", "title", "subcategory", "category", "licence", "evidence"):
        p.add_argument("--" + f)
    p.add_argument("--rights", choices=RIGHTS); p.add_argument("--authenticity", choices=AUTH)
    p = sub.add_parser("metrics"); p.add_argument("key"); p.add_argument("platform"); p.add_argument("values", nargs="+")
    p = sub.add_parser("backup"); p.add_argument("--to")
    p = sub.add_parser("restore"); p.add_argument("file"); p.add_argument("--into", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "backup":
        print(backup(a.to)); return
    if a.cmd == "restore":
        print(restore(a.file, a.into), "files restored into", a.into); return
    db = load()
    actor = os.environ.get("GITHUB_ACTOR") or "owner"
    if a.cmd == "stats":
        for f in ("stage", "state", "rights", "authenticity"):
            c = {}
            for r in db.values():
                c[r.get(f)] = c.get(r.get(f), 0) + 1
            print(f, c)
        print("records", len(db), "| publication queue", len(publication_queue(db)))
    elif a.cmd == "validate":
        pr = validate(db); print("\n".join(pr[:40]) or f"OK: {len(db)} records valid")
        sys.exit(1 if pr else 0)
    elif a.cmd == "sync":
        print(sync(db), "records changed"); save(db)
    elif a.cmd in ("search", "bulk"):
        rows = search(db, a.creator, a.category, a.platform, a.stage, a.in_state, a.min_score, a.rights, a.text)
        if a.cmd == "search":
            print("\n".join(map(line, rows[: a.limit]))); print(len(rows), "matches")
        else:
            if not any((a.creator, a.category, a.platform, a.stage, a.rights, a.text, a.in_state, a.min_score is not None)):
                raise DBError("bulk needs at least one filter")
            if not a.apply:
                print("\n".join(map(line, rows[:20]))); print(f"DRY RUN: {len(rows)} records would become {a.state}. Add --apply.")
            else:
                n = sum(set_fields(r, actor, a.note, state=a.state, manual_state=True) for r in rows)
                save(db); print(n, "records updated")
    else:
        r = resolve(db, a.key)
        if a.cmd == "show":
            print(json.dumps(r, indent=1, ensure_ascii=False))
        elif a.cmd == "history":
            f = path("db", "history.jsonl")
            for ln in (f.read_text(encoding="utf-8").splitlines() if f.exists() else []):
                if json.loads(ln)["id"] == r["content_id"]:
                    print(ln)
        elif a.cmd == "advance":
            advance(r, a.stage, actor, a.note); save(db); print(r["content_id"], "->", r["stage"])
        elif a.cmd == "edit":
            m = {"notes": "editorial_notes", "hook": "suggested_hook", "title": "suggested_title"}
            up = {m.get(k, k): v for k, v in vars(a).items() if v is not None and k not in ("cmd", "key", "evidence")}
            if a.rights in ("owned", "licensed", "permission_granted") and not (a.licence or r.get("licence")):
                raise DBError("recording owned/licensed/permission rights needs --licence (what proves it)")
            if a.authenticity == "verified_by_review" and not a.evidence:
                raise DBError("verifying authenticity needs --evidence")
            if a.evidence:
                up["authenticity_evidence"] = r.get("authenticity_evidence", []) + [a.evidence]
            if a.rights:
                up["rights_basis"] = f"recorded by {actor} {now()}"
            set_fields(r, actor, "edit", **up); save(db); print("saved")
        elif a.cmd == "metrics":
            vals = {k: float(v) for k, v in (x.split("=", 1) for x in a.values)}
            an = dict(r.get("analytics", {})); an[a.platform] = {**vals, "recorded_at": now()}
            set_fields(r, actor, "metrics", analytics=an); save(db); print("saved")


if __name__ == "__main__":
    try:
        main()
    except DBError as e:
        sys.exit(f"ERROR: {e}")
