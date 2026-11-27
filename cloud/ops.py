"""Operations orchestrator and control centre (Phase 8). Supervises the existing workflows; does not duplicate them.

  python cloud/ops.py run [--job NAME]     run due jobs, check the workflows, alert, rebuild the control centre
  python cloud/ops.py build                only rebuild ops/control_center.html
  python cloud/ops.py pause | resume       global kill switch (also stops cloud posting)
  python cloud/ops.py disable NAME | enable NAME
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT / "bot"), str(ROOT / "music")]
import analytics  # noqa: E402
import contentdb  # noqa: E402
import publisher as P  # noqa: E402

CFG = P.load(ROOT / "config" / "ops.json", {})
OVER = ROOT / "config" / "overrides.json"
STATE = ROOT / "db" / "ops_state.json"
LOG = ROOT / "db" / "ops_log.jsonl"
HTML = ROOT / "ops" / "control_center.html"
UTC = dt.timezone.utc
REPO = os.environ.get("GITHUB_REPOSITORY", "salahemd19/gta6-bot")


def now():
    return dt.datetime.now(UTC)


def log(job, result, detail=""):
    P.append(LOG, {"at": now().isoformat(timespec="seconds"), "job": job, "result": result, "detail": str(detail)[:300]})
    print(f"[{job}] {result} {detail}")


def gh(*args):
    r = subprocess.run(["gh", *args, "--repo", REPO], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-200:])
    return r.stdout


# ------------------------------------------------------------------ jobs
def job_approvals():
    import post_next
    items = P.load(P.MANIFEST, [])
    if not os.environ.get("GH_TOKEN"):
        return "skipped: no GitHub token here"
    changed = post_next.sync_approvals(items)
    if changed:
        P.save(P.MANIFEST, items)
    return "owner decisions applied" if changed else "no new decision"


def candidates():
    """Reviewed footage and what stands between it and production."""
    import factory
    import intelligence
    db = contentdb.load()
    by, used, out = factory.index(db), factory.used_sources(), []
    for cid, rv in intelligence.reviews().items():
        r = by.get(cid)
        if r and rv.get("verdict") == "keep":
            why = factory.blockers(r, rv, used)
            if not why and not r.get("media_url") and not (ROOT.parent / "kickclips" / f"{r['id']}.mp4").exists():
                why = ["source file not retrievable from here"]
            out.append({"id": cid, "creator": r["creator"], "category": r.get("category"), "what": rv.get("action_fr"),
                        "blockers": why, "strength": rv.get("strength", 5)})
    return out


def job_produce():
    conf = P.cfg()["production"]
    if not conf["enabled"]:
        return "production disabled"
    import factory
    ready = [c for c in candidates() if not c["blockers"]]
    made = []
    for _ in range(conf["max_videos_per_run"]):
        pick, creators = [], set()
        for c in sorted(ready, key=lambda c: -c["strength"]):
            if len(pick) < conf["min_clips"] and c["creator"] not in creators:
                pick.append(c)
                creators.add(c["creator"])
        if len(pick) < conf["min_clips"]:
            break
        media = ROOT.parent / "kickclips"
        ordered = factory.countdown(pick)
        meta = factory.produce([c["id"] for c in ordered], media=str(media) if media.exists() else None)
        if not meta["publishable"]:
            raise RuntimeError(f"{meta['id']} failed quality control")
        missing = [p for p, e in meta["exports"].items() if not e["music"].get("id")]
        if missing:
            raise RuntimeError(f"{meta['id']} has no library music for {missing}; not submitted")
        factory.submit(meta)
        made.append(meta["id"])
        ready = [c for c in ready if c not in pick]
    if made:
        return f"produced {', '.join(made)}"
    return (f"waiting: {len(ready)} approved clips ready from {len({c['creator'] for c in ready})} creators; "
            f"{conf['min_clips']} clips from different creators needed")


def job_calendar():
    cal = P.plan()
    return " | ".join(f"{p} {c['filled_today']}/{c['cap']} today" for p, c in cal["platforms"].items())


def job_analytics_collect():
    if not os.environ.get("YT_REFRESH_TOKEN") and not analytics.laptop_token():
        old = ROOT.parent / "stats.csv"  # on the laptop: readings logged by the older collector
        if old.exists():
            return f"{analytics.import_csv(old)} readings imported from the laptop log"
        return "skipped: YouTube credentials only exist in the cloud"
    return f"{analytics.collect_youtube()} YouTube readings (TikTok needs a CSV import)"


def job_analytics_report():
    s = analytics.report()
    return "; ".join(f"{p}: {c['videos']} videos, {c['measured_24h']} with 24 h" for p, c in s["platforms"].items())


JOBS = {"approvals": job_approvals, "produce": job_produce, "calendar": job_calendar,
        "analytics_collect": job_analytics_collect, "analytics_report": job_analytics_report}


def run_jobs(state, over, only=None):
    for name, fn in JOBS.items():
        conf, st = CFG["jobs"][name], state["jobs"].setdefault(name, {"failures": 0})
        if only and name != only:
            continue
        if name in over.get("disabled_jobs", []):
            st["result"] = "disabled by override"
            continue
        last = st.get("last_ok")
        if not only and last and conf["every_h"] and (now() - dt.datetime.fromisoformat(last)).total_seconds() < conf["every_h"] * 3600 - 600:
            continue
        for attempt in range(1, conf["retries"] + 1):
            try:
                result = fn()
                st.update(failures=0, last_ok=now().isoformat(timespec="seconds"), result=result, error=None)
                log(name, "ok", result)
                break
            except (Exception, SystemExit) as e:  # noqa: BLE001 - one job failing must not stop the others
                log(name, f"error (attempt {attempt}/{conf['retries']})", f"{type(e).__name__}: {e}")
                if attempt == conf["retries"]:
                    st.update(failures=st["failures"] + 1, error=str(e)[:300], result="failed")
                    traceback.print_exc()
                else:
                    time.sleep(10 * attempt)


# ------------------------------------------------------------------ monitoring, recovery, notification
def monitor(state):
    if not os.environ.get("GH_TOKEN") and subprocess.run(["gh", "auth", "status"], capture_output=True).returncode:
        return
    for w in CFG["workflows"]:
        st = state["workflows"].setdefault(w["file"], {"name": w["name"]})
        try:
            runs = json.loads(gh("run", "list", "--workflow", w["file"], "--limit", "5", "--json",
                                 "databaseId,status,conclusion,createdAt,url"))
        except Exception as e:  # noqa: BLE001
            st.update(health="unknown", detail=str(e)[:150])
            continue
        done = next((r for r in runs if r["status"] == "completed" and r["conclusion"] != "cancelled"), None)
        newest = dt.datetime.fromisoformat(runs[0]["createdAt"].replace("Z", "+00:00")) if runs else None
        age = (now() - newest).total_seconds() / 3600 if newest else None
        health = "failed" if done and done["conclusion"] != "success" else "stale" if age is None or age > w["max_age_h"] else "ok"
        st.update(health=health, age_h=round(age, 1) if age is not None else None, url=done and done["url"])
        if health == "ok":
            st.pop("recovered", None)
        elif w.get("recover") and os.environ.get("GH_TOKEN"):
            key = f"{health}:{done and done['databaseId']}"
            if st.get("recovered") != key:  # one automatic recovery per incident, then a human
                try:
                    if health == "failed":
                        gh("run", "rerun", str(done["databaseId"]), "--failed")
                    else:
                        gh("workflow", "run", w["file"])
                    st["recovered"] = key
                    log("recovery", "ok", f"{w['file']} was {health}; started again")
                except Exception as e:  # noqa: BLE001
                    log("recovery", "error", f"{w['file']}: {e}")


def alerts(state):
    out = [f"Workflow {w['name']}: {w.get('health')}" for w in state["workflows"].values() if w.get("health") in ("failed", "stale")]
    out += [f"Job {n}: {s.get('error')}" for n, s in state["jobs"].items() if s.get("failures", 0) >= CFG["alert_after_failures"]]
    items = P.load(P.MANIFEST, [])
    out += [f"Publishing failed: {i['id']} on {p}" for i in items for p in P.PLATFORMS if str(i.get(p, "")).startswith("failed:")]
    return sorted(out)


def notify(state, current):
    """One GitHub issue labelled ops-alert in the owner's repository; closed again when everything is healthy."""
    if not os.environ.get("GH_TOKEN") or current == state.get("alerts", []):
        return
    try:
        open_ = json.loads(gh("issue", "list", "--label", "ops-alert", "--state", "open", "--json", "number"))
        body = "\n".join(f"- {a}" for a in current)
        if current and not open_:
            gh("label", "create", "ops-alert", "--color", "B60205", "--force")
            gh("issue", "create", "--title", "Alerte opérations VICECITY INTEL", "--body", body, "--label", "ops-alert")
        elif current:
            gh("issue", "comment", str(open_[0]["number"]), "--body", body)
        elif open_:
            gh("issue", "close", str(open_[0]["number"]), "--comment", "Tout est revenu à la normale.")
        state["alerts"] = current
    except Exception as e:  # noqa: BLE001
        log("notify", "error", e)


# ------------------------------------------------------------------ control centre
def collect():
    db = contentdb.load()
    items = P.load(P.MANIFEST, [])
    cal = P.load(P.CALENDAR, {"platforms": {}, "blocked": []})
    state = P.load(STATE, {"jobs": {}, "workflows": {}})
    day = (now() - dt.timedelta(hours=24)).isoformat()
    fresh = sorted((r for r in db.values() if str(r.get("discovered_at", "")) >= day), key=lambda r: -(r.get("views") or 0))
    unreviewed = sorted((r for r in db.values() if r.get("scores") and r.get("state") == "active" and not r.get("used_in")
                         and r.get("authenticity") != "verified_by_review"), key=lambda r: -r["scores"].get("total", 0))
    count = lambda key: sorted(((k, sum(1 for r in db.values() if r.get(key) == k)) for k in {r.get(key) for r in db.values()}),
                               key=lambda z: -z[1])
    local = now().astimezone(P.tz()).date()
    done_today = {p: sum(1 for i in items if P.kind(i.get(p)) in P.DONE and (t := P.when(i.get(p)))
                         and t.astimezone(P.tz()).date() == local) for p in P.PLATFORMS}
    conf = P.cfg()
    queue = lambda k: [{"id": i["id"], "platform": p, "title": i.get("title"), "status": i.get(p), "issue": i.get("issue"),
                        "slot": i.get(f"slot_{p}")} for i in items for p in P.PLATFORMS if P.kind(i.get(p)) == k]
    return {"generated": now().isoformat(timespec="minutes"), "repo": REPO, "override": P.load(OVER, {}),
            "alerts": alerts(state), "workflows": state["workflows"], "jobs": state["jobs"],
            "targets": [{"platform": p, "done": done_today[p], "cap": conf["levels"][p][conf["level"]], "target": conf["targets"][p]}
                        for p in P.PLATFORMS],
            "discoveries": {"count_24h": len(fresh), "total": len(db),
                            "top": [{"creator": r["creator"], "title": r.get("title"), "views": r.get("views"), "url": r.get("url")}
                                    for r in fresh[:12]]},
            "candidates": candidates(),
            "unreviewed": [{"id": r["content_id"], "creator": r["creator"], "score": r["scores"].get("total"), "url": r.get("url")}
                           for r in unreviewed[:12]],
            "review": queue("review"), "ready": queue("ready"), "published": queue("posted")[-20:], "planned": queue("scheduled")[-20:],
            "calendar": {p: c["days"][:2] for p, c in cal["platforms"].items()}, "blocked": cal.get("blocked", []),
            "rights": count("rights"), "authenticity": count("authenticity"),
            "failures": P.lines(P.ERRORS)[-15:] + [x for x in P.lines(LOG)[-200:] if x["result"].startswith("error")][-15:],
            "log": P.lines(LOG)[-30:], "analytics": P.load(analytics.SUMMARY, {})}


def build():
    data = json.dumps(collect(), ensure_ascii=False).replace("<", "\\u003c")
    tpl = (ROOT / "ops" / "control_template.html").read_text(encoding="utf-8")
    HTML.write_text(tpl.replace("/*DATA*/null", data), encoding="utf-8")


def run(only=None):
    over = P.load(OVER, {})
    state = P.load(STATE, {"jobs": {}, "workflows": {}})
    if over.get("paused"):
        log("ops", "paused", over.get("note", ""))
    else:
        run_jobs(state, over, only)
        monitor(state)
        notify(state, alerts(state))
    P.save(STATE, state)
    rows = P.lines(LOG)
    if len(rows) > 2000:
        LOG.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows[-1500:]), encoding="utf-8")
    build()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "build", "pause", "resume", "disable", "enable"])
    ap.add_argument("name", nargs="?")
    ap.add_argument("--job", choices=list(JOBS))
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.job)
    elif a.cmd == "build":
        build()
    else:
        o = P.load(OVER, {"paused": False, "disabled_jobs": [], "note": ""})
        if a.cmd in ("pause", "resume"):
            o["paused"] = a.cmd == "pause"
        else:
            if a.name not in JOBS:
                raise SystemExit(f"jobs: {', '.join(JOBS)}")
            off = set(o["disabled_jobs"])
            off.add(a.name) if a.cmd == "disable" else off.discard(a.name)
            o["disabled_jobs"] = sorted(off)
        P.save(OVER, o)
        print(o)


if __name__ == "__main__":
    main()
