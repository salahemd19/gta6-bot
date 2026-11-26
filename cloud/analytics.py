"""Analytics and learning loop (Phase 7). Medians, minimum sample sizes, correlation never called causation.

  python cloud/analytics.py collect                      YouTube readings through the channel's own OAuth token
  python cloud/analytics.py import FILE.csv [--platform tiktok]
  python cloud/analytics.py report                       summary + weekly and monthly reports

CSV columns (only title and views are required): platform,key,title,published_at,at,views,likes,comments,shares,
impressions,avg_watch_s,retention,completion,rewatches,followers_gained,followers
(the old stats.csv with ts,platform,title,views,likes,comments imports as it is)
"""
import argparse
import csv
import datetime as dt
import hashlib
import statistics
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "bot")]
import publisher as P  # noqa: E402

ROOT = HERE.parent
METRICS = ROOT / "db" / "metrics.jsonl"
SUMMARY = ROOT / "db" / "analytics_summary.json"
REPORTS = ROOT / "ops" / "reports"
FIELDS = ("views", "likes", "comments", "shares", "impressions", "avg_watch_s", "retention", "completion", "rewatches",
          "followers_gained", "followers")
CHECKPOINTS = {"1h": (1, 0.6), "3h": (3, 1.2), "24h": (24, 5), "7d": (168, 24)}  # target age, tolerance (hours)
MIN_N, MIN_TOTAL = 5, 20
UTC = dt.timezone.utc


def norm(title):
    t = unicodedata.normalize("NFKD", str(title)).encode("ascii", "ignore").decode().lower()
    return " ".join("".join(c if c.isalnum() else " " for c in t.replace("#shorts", "")).split())


def parse(t):
    if not t:
        return None
    d = dt.datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=ZONE())


def ZONE():
    return P.tz()


def store(rows):
    have = {(r["platform"], r["key"], r["at"]) for r in P.lines(METRICS)}
    n = 0
    for r in rows:
        if (r["platform"], r["key"], r["at"]) not in have:
            P.append(METRICS, r)
            have.add((r["platform"], r["key"], r["at"]))
            n += 1
    return n


def collect_youtube(limit=100):
    """Own channel, official API. Needs a refresh token with read scope; says so if it is refused."""
    import requests
    import yt
    h = {"Authorization": f"Bearer {yt.access_token()}"}
    base = "https://www.googleapis.com/youtube/v3/"

    def get(path, **params):
        r = requests.get(base + path, headers=h, params=params, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"YouTube {path} {r.status_code}: {r.text[:160]}")
        return r.json()
    ch = get("channels", part="contentDetails,statistics", mine="true")["items"][0]
    ids, page = [], None
    while len(ids) < limit:
        d = get("playlistItems", part="contentDetails", playlistId=ch["contentDetails"]["relatedPlaylists"]["uploads"],
                maxResults=50, **({"pageToken": page} if page else {}))
        ids += [i["contentDetails"]["videoId"] for i in d["items"]]
        page = d.get("nextPageToken")
        if not page:
            break
    at = dt.datetime.now(UTC).isoformat(timespec="minutes")
    rows = []
    for k in range(0, len(ids), 50):
        for v in get("videos", part="snippet,statistics,status", id=",".join(ids[k:k + 50]))["items"]:
            if v["status"].get("privacyStatus") != "public":
                continue
            s = v["statistics"]
            rows.append({"platform": "youtube", "key": v["id"], "title": v["snippet"]["title"], "at": at,
                         "published_at": v["snippet"]["publishedAt"], "views": int(s.get("viewCount", 0)),
                         "likes": int(s.get("likeCount", 0)), "comments": int(s.get("commentCount", 0)),
                         "followers": int(ch["statistics"].get("subscriberCount", 0)), "source": "youtube_api"})
    return store(rows)


def import_csv(path, platform=None):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            title, at = r.get("title") or "", r.get("at") or r.get("ts")
            if not title or not r.get("views") or not at:
                continue
            p = (r.get("platform") or platform or "").lower()
            row = {"platform": p, "key": r.get("key") or "t-" + hashlib.sha1(norm(title).encode()).hexdigest()[:12],
                   "title": title, "at": parse(at).astimezone(UTC).isoformat(timespec="minutes"),
                   "published_at": r.get("published_at") or None, "source": "csv"}
            for m in FIELDS:
                if r.get(m) not in (None, ""):
                    row[m] = float(str(r[m]).replace(",", ".").replace("%", ""))
            rows.append(row)
    return store(rows)


def window_of(platform, t):
    hm = t.astimezone(ZONE()).strftime("%H:%M")
    return next((w["name"] for w in P.cfg()["windows"].get(platform, []) if w["from"] <= hm < w["to"]), "outside windows")


def publications():
    """One row per published video: its readings joined to what the queue knows about how it was made."""
    items = P.load(P.MANIFEST, [])
    meta = {}
    for i in items:
        for p in P.PLATFORMS:
            if i.get(f"{p}_url"):
                meta[(p, i[f"{p}_url"].rstrip("/").split("/")[-1])] = i
            meta[(p, norm(i.get("title", ""))[:60])] = i
    pubs = {}
    for r in P.lines(METRICS):
        k = (r["platform"], r["key"])
        x = pubs.setdefault(k, {"platform": r["platform"], "key": r["key"], "title": r["title"], "published_at": None, "readings": []})
        x["published_at"] = x["published_at"] or r.get("published_at")
        x["readings"].append(r)
    for (p, key), x in pubs.items():
        item = meta.get((p, key)) or meta.get((p, norm(x["title"])[:60])) or {}
        if not x["published_at"]:
            t = P.when(item.get(p)) if P.kind(item.get(p)) in P.DONE else None
            x["published_at"] = t.isoformat() if t else None
        pub = parse(x["published_at"]) if x["published_at"] else None
        x["readings"].sort(key=lambda r: r["at"])
        x["latest"] = x["readings"][-1]
        x["checkpoints"] = {}
        if pub:
            for name, (target, tol) in CHECKPOINTS.items():
                near = [(abs((parse(r["at"]) - pub).total_seconds() / 3600 - target), r) for r in x["readings"]]
                d, r = min(near, key=lambda z: z[0])
                if d <= tol:
                    x["checkpoints"][name] = {m: r[m] for m in FIELDS if m in r}
        dur = item.get("duration_s")
        creators = item.get("streamer", "")
        x["dims"] = {
            "category": item.get("category"), "series": item.get("series"), "hook": item.get("hook"),
            "format": item.get("type"),
            "length": None if not dur else "under 20 s" if dur < 20 else "20-34 s" if dur < 35 else "35 s and more",
            "source_type": None if not item else ("compilation of several creators" if "," in creators else "single creator"),
            "weekday": pub.astimezone(ZONE()).strftime("%A") if pub else None,
            "window": window_of(p, pub) if pub else None}
        x["effort_s"] = item.get("render_seconds")
        x["item"] = item.get("id")
    return list(pubs.values())


def value(x):
    """The comparable number: views at 24 h; none if we never read it near 24 h."""
    return (x["checkpoints"].get("24h") or {}).get("views")


def compare(pubs):
    out = {}
    for p in P.PLATFORMS:
        rows = [x for x in pubs if x["platform"] == p]
        measured = [x for x in rows if value(x) is not None]
        overall = statistics.median(map(value, measured)) if measured else None
        dims = {}
        for d in ("category", "series", "hook", "format", "length", "source_type", "weekday", "window"):
            groups = {}
            for x in measured:
                if x["dims"].get(d):
                    groups.setdefault(x["dims"][d], []).append(value(x))
            dims[d] = sorted(({"group": g, "n": len(v), "median_24h": statistics.median(v),
                               "vs_platform": round(statistics.median(v) / overall, 2) if overall else None,
                               "enough": len(v) >= MIN_N} for g, v in groups.items()), key=lambda z: -z["median_24h"])
        ages = [x["latest"]["views"] for x in rows]
        likes = [100 * x["latest"].get("likes", 0) / x["latest"]["views"] for x in rows if x["latest"]["views"] >= 50]
        per_f = [value(x) / x["checkpoints"]["24h"]["followers"] for x in measured if x["checkpoints"]["24h"].get("followers")]
        out[p] = {"videos": len(rows), "measured_24h": len(measured), "median_24h": overall,
                  "median_latest_views": statistics.median(ages) if ages else None,
                  "median_like_rate_pct": round(statistics.median(likes), 2) if likes else None,
                  "views_per_follower_median": round(statistics.median(per_f), 2) if per_f else None,
                  "top_share_of_views": round(max(ages) / sum(ages), 2) if sum(ages) else None,
                  "not_collected": [m for m in FIELDS if not any(m in x["latest"] for x in rows)],
                  "dimensions": dims}
    return out


def advice(comp, pubs):
    out = []
    for p, c in comp.items():
        if c["measured_24h"] < MIN_TOTAL:
            out.append({"platform": p, "level": "wait", "text": f"{c['measured_24h']} videos have a 24 h reading; "
                        f"{MIN_TOTAL} are needed before recommending changes."})
            continue
        for d, groups in c["dimensions"].items():
            good = [g for g in groups if g["enough"]]
            if len(good) >= 2 and good[0]["median_24h"] >= 1.3 * max(1, good[-1]["median_24h"]):
                out.append({"platform": p, "level": "test", "text":
                            f"{d}: '{good[0]['group']}' (n={good[0]['n']}, median {good[0]['median_24h']:.0f}) is ahead of "
                            f"'{good[-1]['group']}' (n={good[-1]['n']}, median {good[-1]['median_24h']:.0f}). "
                            "Give it more slots and keep measuring; this is a correlation."})
        series = {}
        for x in sorted((x for x in pubs if x["platform"] == p and value(x) is not None), key=lambda x: x["published_at"]):
            series.setdefault(x["dims"].get("series") or x["dims"].get("category"), []).append(value(x))
        for s, v in series.items():
            if s and len(v) >= 10 and statistics.median(v[-5:]) < 0.7 * statistics.median(v[-10:-5]):
                out.append({"platform": p, "level": "watch", "text": f"Possible audience fatigue on {s}: median of the last 5 "
                            "is more than 30% below the 5 before."})
    return out or [{"platform": "all", "level": "wait", "text": "No group differs enough to act on."}]


def experiments(comp):
    conf = P.load(ROOT / "config" / "experiments.json", {})
    out = []
    for e in conf.get("experiments", []):
        groups = comp[e["platform"]]["dimensions"].get(e["dimension"], [])
        ready = [g for g in groups if g["n"] >= conf["min_samples_per_arm"]]
        out.append({**e, "arms": [{"group": g["group"], "n": g["n"], "median_24h": g["median_24h"]} for g in groups],
                    "status": "readable" if len(ready) >= 2 else "collecting"})
    return out


def report(now=None):
    now = now or dt.datetime.now(UTC)
    pubs = publications()
    comp = compare(pubs)
    summary = {"generated": now.isoformat(timespec="minutes"), "platforms": comp, "advice": advice(comp, pubs),
               "experiments": experiments(comp),
               "scoring": "Score weights are not changed automatically: needs at least 30 published factory videos with 24 h views.",
               "recent": sorted(({"platform": x["platform"], "title": x["title"], "published_at": x["published_at"],
                                  "views": x["latest"]["views"], "views_24h": value(x), "item": x["item"]} for x in pubs),
                                key=lambda r: r["published_at"] or "", reverse=True)[:25]}
    P.save(SUMMARY, summary)
    REPORTS.mkdir(parents=True, exist_ok=True)
    y, w, _ = now.isocalendar()
    for name, days, title in ((f"weekly-{y}-W{w:02d}.md", 7, "Weekly report"), (f"monthly-{now:%Y-%m}.md", 30, "Monthly strategic review")):
        since = now - dt.timedelta(days=days)
        period = [x for x in pubs if x["published_at"] and parse(x["published_at"]) >= since]
        md = [f"# VICECITY INTEL — {title} ({now:%Y-%m-%d})", ""]
        for p in P.PLATFORMS:
            rows = [x for x in period if x["platform"] == p]
            v = [value(x) for x in rows if value(x) is not None]
            best = max(rows, key=lambda x: x["latest"]["views"], default=None)
            md += [f"## {p.title()}", f"- Videos published in the last {days} days with data: {len(rows)}",
                   f"- Median 24 h views: {statistics.median(v):.0f} (n={len(v)})" if v else "- Median 24 h views: no 24 h readings yet",
                   f"- Most viewed: {best['title']} ({best['latest']['views']:.0f})" if best else "- Most viewed: none",
                   f"- Not collected: {', '.join(comp[p]['not_collected']) or 'nothing missing'}", ""]
        md += ["## Recommendations"] + [f"- [{a['platform']}] {a['text']}" for a in summary["advice"]]
        md += ["", "## Experiments"] + [f"- {e['id']}: {e['status']} ({', '.join(f'{a['group']} n={a['n']}' for a in e['arms']) or 'no data'})"
                                        for e in summary["experiments"]]
        md += ["", "Medians only; no result here proves a cause, and nothing guarantees reach.", ""]
        (REPORTS / name).write_text("\n".join(md), encoding="utf-8")
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["collect", "import", "report"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--platform")
    a = ap.parse_args()
    if a.cmd == "collect":
        print(collect_youtube(), "new YouTube readings")
    elif a.cmd == "import":
        print(import_csv(a.file, a.platform), "new readings")
    else:
        s = report()
        for p, c in s["platforms"].items():
            print(p, c["videos"], "videos,", c["measured_24h"], "with 24h; median latest", c["median_latest_views"])
        for x in s["advice"]:
            print("-", x["platform"], x["text"])


if __name__ == "__main__":
    main()
