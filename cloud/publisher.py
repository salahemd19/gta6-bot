"""France-first publishing calendar (Phase 6). Europe/Paris, CET/CEST handled by zoneinfo.

  python cloud/publisher.py plan [--days 3] [--dry-run]    build both calendars and give approved items a slot
  python cloud/publisher.py due                            work for the posting task, as JSON
  python cloud/publisher.py status                         today's calendar and what is blocked
  python cloud/publisher.py mark <id> <platform> posted|scheduled|failed [--url U] [--error TEXT] [--at ISO]
  python cloud/publisher.py hold <id> "<reason>"   |   release <id>

The queue (queue/manifest.json) is the single source of truth. bot/post_next.py (cloud) and the laptop task post
what the calendar assigns. Nothing is scheduled without owner approval, publishable rights and no open factual or
authenticity flag.
"""
import argparse
import datetime as dt
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CFG_F = ROOT / "config" / "publishing.json"
MANIFEST = ROOT / "queue" / "manifest.json"
CALENDAR = ROOT / "queue" / "calendar.json"
HISTORY = ROOT / "db" / "publish_history.jsonl"
ERRORS = ROOT / "db" / "publish_errors.jsonl"
PLATFORMS = ("youtube", "tiktok")
RIGHTS = {"owned", "licensed", "permission_granted", "credited_third_party"}
DONE = ("posted", "scheduled")
UTC = dt.timezone.utc


def load(f, default):
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else default


def save(f, obj):
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(f.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


def lines(f):
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []


def append(f, row):
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as h:
        h.write(json.dumps(row, ensure_ascii=False) + "\n")


def cfg():
    return load(CFG_F, {})


def tz():
    return ZoneInfo(cfg()["timezone"])


def kind(status):
    s = str(status or "")
    for k, starts in (("posted", ("posted",)), ("scheduled", ("scheduled",)), ("ready", ("pending", "failed (retry")),
                      ("review", ("awaiting",)), ("failed", ("failed",)), ("held", ("hold",))):
        if s.startswith(starts):
            return k
    return "closed"


def when(status):
    m = re.search(r"\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?(?:\+\d\d:\d\d|Z)?", str(status or ""))
    if not m:
        return None
    t = dt.datetime.fromisoformat(m.group().replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def gate(item):
    """Why this item may not be published (empty list = allowed once the owner approved it)."""
    why = []
    if item.get("rights", "unverified") not in RIGHTS:
        why.append(f"rights {item.get('rights', 'unverified')}")
    if item.get("authenticity") in ("unresolved", "not_gta6"):
        why.append(f"authenticity {item['authenticity']}")
    if item.get("factual_issue"):
        why.append(f"factual issue: {item['factual_issue']}")
    if item.get("hold"):
        why.append(f"manual hold: {item['hold']}")
    return why


def keys(item):
    """What makes two items the same footage."""
    out = {s.get("content_id") or s.get("url") for s in item.get("sources", [])}
    return {k for k in out if k} or {item["id"]}


def clashes(item, others):
    title = item.get("title", "").lower()
    for o in others:
        if o["id"] == item["id"]:
            continue
        if keys(item) & keys(o):
            return f"same footage as {o['id']}"
        if title and title == o.get("title", "").lower():
            return f"same title as {o['id']}"
    return None


def slot_times(day, platform, count, conf):
    """Spread `count` posts over the platform's windows in proportion to their weight."""
    wins = conf["windows"][platform]
    total = sum(w["weight"] for w in wins)
    share = [count * w["weight"] / total for w in wins]
    n = [int(s) for s in share]
    for i in sorted(range(len(wins)), key=lambda i: -(share[i] - n[i]))[: count - sum(n)]:
        n[i] += 1
    gap, out, last = dt.timedelta(minutes=conf["min_gap_minutes"][platform]), [], None
    for w, k in zip(wins, n):
        a, b = (dt.datetime.combine(day, dt.time.fromisoformat(w[x]), tzinfo=ZoneInfo(conf["timezone"])) for x in ("from", "to"))
        for j in range(k):
            t = a + (b - a) * ((j + 0.5) / k)
            t = t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0)
            if last and t - last < gap:
                t = last + gap
            if t < b:
                out.append((t, w["name"]))
                last = t
    return out


def priority(item, previous, day_counts):
    score = float(item.get("score") or 0)
    cat = item.get("category") or item.get("type")
    score -= 3 if cat and cat == previous else 0           # never the same pillar twice in a row if possible
    score -= 1.0 * day_counts.get(cat, 0)                  # balance the day
    created = when(item.get("created"))
    if created:
        score += max(0.0, 2 - (dt.datetime.now(UTC) - created).total_seconds() / 86400)  # fresh first
    return score


def package(item, platform):
    music = (item.get("music") or {}).get(platform)
    if platform == "youtube":
        return {"video_url": item.get("video_url"), "title": item.get("title", "")[:100],
                "description": item.get("youtube_description", ""), "tags": item.get("tags", ""), "music": music}
    return {"video_url": item.get("video_url_tiktok") or item.get("video_url"), "caption": item.get("tiktok_caption", ""),
            "music": music}


def plan(days=3, dry=False, now=None):
    conf, items = cfg(), load(MANIFEST, [])
    now = now or dt.datetime.now(UTC)
    local_now = now.astimezone(ZoneInfo(conf["timezone"]))
    cal = {"generated": now.isoformat(timespec="minutes"), "level": conf["level"], "timezone": conf["timezone"],
           "platforms": {}, "blocked": [], "waiting_approval": [], "missed": []}
    for p in PLATFORMS:
        cap = conf["levels"][p][conf["level"]]
        done = [i for i in items if kind(i.get(p)) in DONE]
        ready = []
        for i in items:
            k = kind(i.get(p))
            if k not in ("ready", "review"):
                continue
            why = gate(i) or ([c] if (c := clashes(i, done)) else [])
            if why:
                cal["blocked"].append({"id": i["id"], "platform": p, "why": "; ".join(why)})
            elif k == "review":
                cal["waiting_approval"].append({"id": i["id"], "platform": p, "issue": i.get("issue"), "title": i.get("title")})
            else:
                old = when(i.get(f"slot_{p}"))
                if old and now - old > dt.timedelta(minutes=conf["missed_after_minutes"]):
                    cal["missed"].append({"id": i["id"], "platform": p, "slot": old.isoformat()})
                ready.append(i)
        placed, schedule = list(done), []
        for d in range(days):
            day = local_now.date() + dt.timedelta(days=d)
            fixed = [(t.astimezone(local_now.tzinfo), i) for i in done if (t := when(i.get(p)))
                     and t.astimezone(local_now.tzinfo).date() == day]
            counts, previous, rows = {}, None, []
            for t, i in fixed:
                c = i.get("category") or i.get("type")
                counts[c] = counts.get(c, 0) + 1
                rows.append({"local": t.strftime("%H:%M"), "utc": t.astimezone(UTC).isoformat(timespec="minutes"),
                             "window": "fixed", "id": i["id"], "status": kind(i.get(p)), "title": i.get("title")})
            gap = dt.timedelta(minutes=conf["min_gap_minutes"][p])
            soon = local_now + dt.timedelta(minutes=conf["lead_minutes"])
            for i in list(ready):  # an assigned slot is kept while there is still time to schedule it
                t = when(i.get(f"slot_{p}"))
                if t and t >= soon and t.astimezone(local_now.tzinfo).date() == day and len(fixed) < cap and not clashes(i, placed):
                    t = t.astimezone(local_now.tzinfo)
                    ready.remove(i)
                    placed.append(i)
                    fixed.append((t, i))
                    c = i.get("category") or i.get("type")
                    counts[c] = counts.get(c, 0) + 1
                    hm = t.strftime("%H:%M")
                    rows.append({"local": hm, "utc": t.astimezone(UTC).isoformat(timespec="minutes"), "id": i["id"],
                                 "window": next((w["name"] for w in conf["windows"][p] if w["from"] <= hm < w["to"]), "kept"),
                                 "status": "assigned", "title": i.get("title"), "package": package(i, p)})
            free = max(0, cap - len(fixed))
            for t, window in slot_times(day, p, cap, conf):
                if free == 0 or t < soon or any(abs(t - f) < gap for f, _ in fixed):
                    continue
                free -= 1
                row = {"local": t.strftime("%H:%M"), "utc": t.astimezone(UTC).isoformat(timespec="minutes"), "window": window,
                       "id": None, "status": "empty", "title": None}
                pool = [i for i in ready if not clashes(i, placed)]
                if pool:
                    best = max(pool, key=lambda i: priority(i, previous, counts))
                    ready.remove(best)
                    placed.append(best)
                    previous = best.get("category") or best.get("type")
                    counts[previous] = counts.get(previous, 0) + 1
                    row.update(id=best["id"], status="assigned", title=best.get("title"), package=package(best, p))
                    best[f"slot_{p}"] = row["utc"]
                rows.append(row)
            schedule.append({"date": day.isoformat(), "cap": cap, "slots": sorted(rows, key=lambda r: r["local"])})
        for i in ready:  # approved but no room or duplicate of an assigned one
            i.pop(f"slot_{p}", None)
            cal["blocked"].append({"id": i["id"], "platform": p, "why": "no free slot or same footage already planned"})
        today = schedule[0]["slots"]
        cal["platforms"][p] = {"days": schedule, "target": conf["targets"][p], "cap": cap,
                               "filled_today": sum(r["status"] != "empty" for r in today),
                               "empty_next_days": sum(r["status"] == "empty" for s in schedule for r in s["slots"])}
    if not dry:
        save(MANIFEST, items)
        save(CALENDAR, cal)
        for m in cal["missed"]:
            append(ERRORS, {"at": now.isoformat(timespec="seconds"), "type": "missed_slot", **m, "action": "rescheduled"})
        record(items, now)
    return cal


def record(items=None, now=None):
    """Append every status change to the publishing history (and failures to the error log)."""
    items = items if items is not None else load(MANIFEST, [])
    now = (now or dt.datetime.now(UTC)).isoformat(timespec="seconds")
    last = {(h["id"], h["platform"]): h["status"] for h in lines(HISTORY)}
    n = 0
    for i in items:
        for p in PLATFORMS:
            s = i.get(p)
            if s and last.get((i["id"], p)) != s:
                row = {"at": now, "id": i["id"], "platform": p, "status": s, "slot": i.get(f"slot_{p}"),
                       "url": i.get(f"{p}_url"), "category": i.get("category"), "title": i.get("title")}
                append(HISTORY, row)
                if str(s).startswith("failed"):
                    append(ERRORS, {"at": now, "type": "publish_failed", "id": i["id"], "platform": p, "error": s})
                n += 1
    return n


def mark(item_id, platform, state, url=None, error=None, at=None):
    items = load(MANIFEST, [])
    i = next((x for x in items if x["id"] == item_id), None)
    if not i:
        raise SystemExit(f"unknown item {item_id}")
    if state in DONE:
        why = gate(i)
        if kind(i.get(platform)) == "review":
            why.append("not approved yet")
        if why:
            raise SystemExit(f"refused: {'; '.join(why)}")
        i[platform] = f"{state} {at or dt.datetime.now(UTC).isoformat(timespec='minutes')}"
        if url:
            i[f"{platform}_url"] = url
    else:
        tries = i.get(f"{platform}_tries", 0) + 1
        i[f"{platform}_tries"] = tries
        i[platform] = (f"failed (retry {tries}/3): " if tries < 3 else "failed: ") + (error or "unknown")[:120]
    save(MANIFEST, items)
    record(items)
    return i[platform]


def hold(item_id, reason):
    items = load(MANIFEST, [])
    i = next(x for x in items if x["id"] == item_id)
    if reason:
        i["hold"] = reason
        for p in PLATFORMS:
            i.pop(f"slot_{p}", None)
    else:
        i.pop("hold", None)
    save(MANIFEST, items)


def due():
    """What the posting task has to do now: apply owner decisions, refresh the calendar, list today's work."""
    import os
    import subprocess
    import sys
    if not os.environ.get("GH_TOKEN"):
        os.environ["GH_TOKEN"] = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
    sys.path.insert(0, str(ROOT / "bot"))
    import post_next
    items = load(MANIFEST, [])
    if post_next.sync_approvals(items):
        save(MANIFEST, items)
    cal, items = plan(), load(MANIFEST, [])
    now_ = dt.datetime.now(UTC)
    out = {"schedule": [], "verify": [], "prescreen": []}
    for p, c in cal["platforms"].items():
        for r in c["days"][0]["slots"]:
            if r["status"] == "assigned":
                out["schedule"].append({"id": r["id"], "platform": p, "paris": r["local"], "utc": r["utc"], **r["package"]})
    for i in items:
        for p in PLATFORMS:
            t = when(i.get(p))
            if kind(i.get(p)) == "scheduled" and t and dt.timedelta(minutes=10) < now_ - t < dt.timedelta(hours=36):
                out["verify"].append({"id": i["id"], "platform": p, "slot": t.isoformat(), "title": i.get("title")})
    out["prescreen"] = sorted({w["issue"] for w in cal["waiting_approval"] if w.get("issue")})
    try:
        import analytics
        out["youtube_readings"] = analytics.collect_youtube()  # cheap, hourly, so 1 h / 3 h / 24 h readings exist
    except Exception as e:  # noqa: BLE001
        out["youtube_readings"] = f"not collected: {str(e)[:120]}"
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "status", "due", "mark", "hold", "release"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--url")
    ap.add_argument("--error")
    ap.add_argument("--at")
    a = ap.parse_args()
    if a.cmd == "due":
        print(json.dumps(due(), ensure_ascii=False, indent=1))
    elif a.cmd == "mark":
        print(mark(*a.args[:3], url=a.url, error=a.error, at=a.at))
    elif a.cmd == "hold":
        hold(a.args[0], a.args[1])
    elif a.cmd == "release":
        hold(a.args[0], None)
    else:
        cal = plan(a.days, a.cmd == "status" or a.dry_run)
        for p, c in cal["platforms"].items():
            print(f"{p}: cap {c['cap']}/day (target {c['target']}), today {c['filled_today']} filled")
            for r in c["days"][0]["slots"]:
                print(f"  {r['local']} {r['window']:<15} {r['status']:<9} {r['id'] or ''}")
        print("waiting approval:", len(cal["waiting_approval"]), "| blocked:", len(cal["blocked"]), "| missed:", len(cal["missed"]))


if __name__ == "__main__":
    main()
