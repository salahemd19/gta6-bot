"""VICECITY INTEL discovery radar (Phase 2). Runs hourly; no video download.

Sources: Kick (clips, live streams, chat spikes), public RSS (news, trends, YouTube channel feeds), and Twitch /
YouTube Data / Reddit connectors that switch on only when their keys exist. Every source reports its real status.

Writes db/clips.json (clip candidates), db/creators.json, db/items.json (streams, live moments, videos, articles),
db/topics.json, db/radar_log.json and ops/radar_dashboard.html.

Run from the repo root:  python cloud/radar.py
"""
import datetime as dt
import html
import json
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import engine  # noqa: E402
import kick_api  # noqa: E402

CFG = json.loads((ROOT / "config" / "radar.json").read_text(encoding="utf-8"))
DB = ROOT / "db"
UA = {"User-Agent": "vicecity-radar/1.0"}
KICK_UA = engine.UA
NOW = dt.datetime.now(dt.timezone.utc)
STATUS = {}  # source -> {"state": ok|error|not_connected|unavailable, "detail": str, "new": int}


def iso(t=None):
    return (t or NOW).isoformat(timespec="seconds")


def age_hours(s):
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if not t.tzinfo:
            t = t.replace(tzinfo=dt.timezone.utc)
        return max(0.25, (NOW - t).total_seconds() / 3600)
    except ValueError:
        return 24.0


def load(name, default):
    f = DB / name
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else default


def save(name, obj):
    DB.mkdir(exist_ok=True)
    (DB / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


def topics_of(text):
    t = (text or "").lower()
    return [k for k, v in CFG["topics"].items() if re.search(v["regex"], t)]


def add_item(items, key, rec):
    """Insert once (duplicate-safe); refresh metrics on later sightings."""
    rec["topics"] = topics_of(rec.get("title"))
    if key in items:
        items[key].update({k: v for k, v in rec.items() if k != "discovered_at"})
        items[key]["last_seen"] = iso()
        return 0
    items[key] = {**rec, "discovered_at": iso(), "last_seen": iso()}
    return 1


def run_source(name, fn, *args):
    try:
        n = fn(*args)
        if name not in STATUS:
            STATUS[name] = {"state": "ok", "detail": "", "new": n or 0}
    except (Exception, SystemExit) as e:  # noqa: BLE001 - one broken source never stops the radar
        STATUS[name] = {"state": "error", "detail": re.sub(r"key=[\w-]+", "key=***", str(e))[:160], "new": 0}
    print(name, STATUS[name], flush=True)


# ------------------------------------------------------------------ Kick
def kick_clips(clips):
    before = len(clips)
    snap = {k: r.get("views", 0) for k, r in clips.items()}
    for sort, window in CFG["kick"]["clip_sorts"]:
        cur = None
        for _ in range(CFG["kick"]["clip_pages"]):
            p = {"sort": sort, "time": window, **({"cursor": cur} if cur else {})}
            r = requests.get(engine.KICK_CLIPS, params=p, headers=KICK_UA, timeout=30)
            r.raise_for_status()
            data = r.json()
            for c in data.get("clips", []):
                engine.record_kick_clip(clips, c)
            cur = data.get("nextCursor")
            time.sleep(0.5)
            if not cur:
                break
    for k, r in clips.items():  # growth since the previous scan = "emerging" signal
        prev_t = r.get("seen_at")
        if k in snap and prev_t and age_hours(prev_t) >= 0.5:
            r["views_per_hour_recent"] = round(max(0, r.get("views", 0) - snap[k]) / age_hours(prev_t), 1)
        r["seen_at"] = iso()
    return len(clips) - before


def kick_live(items, creators):
    env = {k: os.environ.get(k) for k in ("KICK_CLIENT_ID", "KICK_CLIENT_SECRET")}
    if not all(env.values()):
        STATUS["kick_live"] = {"state": "not_connected", "detail": "KICK_CLIENT_ID/SECRET not set in this environment", "new": 0}
        STATUS["kick_chat"] = {"state": "not_connected", "detail": "needs the live list", "new": 0}
        return
    tok = kick_api.get_token(env)
    live = kick_api.api_get(tok, "livestreams", category_id=13155, limit=CFG["kick"]["live_limit"],
                            sort="viewer_count").get("data", [])
    new = 0
    for s in live:
        slug = s.get("slug")
        new += add_item(items, f"kick-live:{slug}:{s.get('started_at')}", {
            "source": "kick", "type": "live_stream", "creator": slug, "title": s.get("stream_title", ""),
            "url": f"https://kick.com/{slug}", "published_at": s.get("started_at"),
            "viewers": s.get("viewer_count", 0), "language": s.get("language")})
        c = creators.setdefault(f"kick:{slug}", {})
        c.update({"language": s.get("language"), "last_live": iso(), "live_viewers": s.get("viewer_count", 0)})
        c["peak_viewers"] = max(c.get("peak_viewers", 0), s.get("viewer_count", 0))
    STATUS["kick_live"] = {"state": "ok", "detail": f"{len(live)} live GTA 6 streams", "new": new}
    run_source("kick_chat", kick_chat, items, live[: CFG["kick"]["chat_streams"]])


def kick_chat(items, streams):
    """Live viral moments: where the chat of the biggest streams spiked in the last few minutes."""
    import chat_signal
    secs, new, read, failed = CFG["kick"]["chat_seconds"], 0, 0, []
    for s in streams:
        slug = s.get("slug")
        try:
            start = time.time() - secs - 20
            ch = s.get("channel_id")
            probe = requests.get(f"https://kick.com/api/v2/channels/{ch}/messages", headers=KICK_UA, timeout=20,
                                 params={"start_time": dt.datetime.fromtimestamp(start, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")})
            if probe.status_code in (403, 429):  # Kick refused us: stop, never work around it
                STATUS["kick_chat"] = {"state": "blocked", "new": new, "detail": f"Kick refused the chat endpoint (HTTP {probe.status_code}); "
                                       "not retried until the next run"}
                return new
            chat = chat_signal.fetch(slug, start, secs, ch)
        except Exception as e:  # noqa: BLE001
            print("chat", slug, "unavailable:", str(e)[:80])
            failed.append(slug)
            continue
        n, offs = len(chat["offsets"]), chat["offsets"]
        read += n
        if n < 20:
            continue
        bins = [0] * (secs // 15)
        for t in offs:
            bins[min(len(bins) - 1, int(t // 15))] += 1
        peak = max(range(len(bins)), key=lambda i: bins[i])
        ratio = bins[peak] / max(1.0, sum(bins) / len(bins))
        hype = sum(1 for t in chat["hype"] if peak * 15 <= t < (peak + 1) * 15)
        if ratio >= 1.6 or hype >= 8:
            at = dt.datetime.fromtimestamp(start + peak * 15, dt.timezone.utc)
            new += add_item(items, f"kick-moment:{slug}:{at.strftime('%Y%m%d%H%M')}", {
                "source": "kick", "type": "live_moment", "creator": slug, "title": s.get("stream_title", ""),
                "url": f"https://kick.com/{slug}", "published_at": iso(at), "language": s.get("language"),
                "viewers": s.get("viewer_count", 0), "chat_spike_ratio": round(ratio, 2), "hype_messages": hype})
    if streams and not read:
        raise RuntimeError("chat history returned no messages for any sampled stream")
    STATUS["kick_chat"] = {"state": "ok", "new": new, "detail": f"{len(streams) - len(failed)} of {len(streams)} chats read"
                           + (f"; no channel data for {', '.join(failed)}" if failed else "")}
    return new


# ------------------------------------------------------------------ public feeds
def parse_feed(url):
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for e in root.iter():
        tag = e.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        d = {}
        for ch in e:
            k = ch.tag.split("}")[-1]
            if k == "link":
                d["link"] = ch.get("href") or (ch.text or "").strip()
            elif k in ("title", "pubDate", "published", "videoId", "source", "guid"):
                d[k] = (ch.text or "").strip()
        out.append(d)
    return out


def rfc_or_iso(s):
    if not s:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return s


def news(items):
    for f in CFG["news_feeds"]:
        def one(f=f):
            n = 0
            for d in parse_feed(f["url"]):
                if f.get("must_match") and not re.search(f["must_match"], d.get("title", "").lower()):
                    continue
                n += add_item(items, "news:" + (d.get("guid") or d.get("link", "")), {
                    "source": f["name"], "type": "article", "creator": d.get("source") or f["name"],
                    "title": d.get("title", ""), "url": d.get("link"), "language": f["lang"],
                    "published_at": rfc_or_iso(d.get("pubDate") or d.get("published"))})
            return n
        run_source(f["name"], one)


def youtube_feeds(items, creators):
    n = 0
    for ch in CFG["youtube_channels"]:
        for d in parse_feed(f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['id']}"):
            if not re.search(r"gta|grand theft auto|vice city|leonida", d.get("title", "").lower()):
                continue
            n += add_item(items, "yt:" + d.get("videoId", d.get("link", "")), {
                "source": "youtube", "type": "video", "creator": ch["name"], "title": d.get("title", ""),
                "url": d.get("link"), "published_at": d.get("published")})
        creators.setdefault(f"youtube:{ch['name']}", {})["monitored"] = True
    return n


# ------------------------------------------------------------------ keyed connectors (off until keys exist)
def need(name, *keys):
    vals = [os.environ.get(k) for k in keys]
    if not all(vals):
        STATUS[name] = {"state": "not_connected", "detail": "add secret(s): " + ", ".join(keys), "new": 0}
        return None
    return vals


def twitch(items):
    v = need("twitch", "TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET")
    if not v:
        return 0
    tok = requests.post("https://id.twitch.tv/oauth2/token", timeout=20, data={
        "client_id": v[0], "client_secret": v[1], "grant_type": "client_credentials"}).json()["access_token"]
    h = {"Client-Id": v[0], "Authorization": f"Bearer {tok}"}
    g = requests.get("https://api.twitch.tv/helix/games", params={"name": CFG["twitch_game"]}, headers=h, timeout=20).json()["data"][0]["id"]
    since = (NOW - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get("https://api.twitch.tv/helix/clips", headers=h, timeout=20,
                     params={"game_id": g, "first": 100, "started_at": since}).json()["data"]
    return sum(add_item(items, "twitch:" + c["id"], {
        "source": "twitch", "type": "clip", "creator": c["broadcaster_name"], "title": c["title"], "url": c["url"],
        "published_at": c["created_at"], "views": c["view_count"], "language": c["language"]}) for c in r)


def youtube_search(items):
    v = need("youtube_search", "YT_API_KEY")
    if not v:
        return 0
    # search costs 100 quota units per call: four times a day only (a manual run always searches)
    if NOW.hour % 6 and os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        STATUS["youtube_search"] = {"state": "ok", "detail": "skipped this hour to save quota", "new": 0}
        return 0
    n = 0
    since = (NOW - dt.timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for q, ev in (("GTA 6", None), ("GTA 6 secret", None), ("GTA 6", "live")):
        p = {"part": "snippet", "q": q, "type": "video", "maxResults": 50, "key": v[0], "order": "viewCount"}
        p.update({"eventType": ev} if ev else {"publishedAfter": since})
        data = requests.get("https://www.googleapis.com/youtube/v3/search", params=p, timeout=20).json()
        if "error" in data:  # show the API's reason; never print the request URL, it carries the key
            raise RuntimeError(f"YouTube API {data['error'].get('code')}: {data['error'].get('message', '')[:100]}")
        for it in data.get("items", []):
            s, vid = it["snippet"], it["id"]["videoId"]
            n += add_item(items, "yt:" + vid, {
                "source": "youtube", "type": "live_stream" if ev else "video", "creator": s["channelTitle"],
                "title": html.unescape(s["title"]), "url": f"https://youtube.com/watch?v={vid}", "published_at": s["publishedAt"]})
    return n


def reddit(items):
    v = need("reddit", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET")
    if not v:
        return 0
    tok = requests.post("https://www.reddit.com/api/v1/access_token", auth=tuple(v), headers=UA, timeout=20,
                        data={"grant_type": "client_credentials"}).json()["access_token"]
    h = {**UA, "Authorization": f"bearer {tok}"}
    n = 0
    for sub in CFG["reddit_subs"]:
        data = requests.get(f"https://oauth.reddit.com/r/{sub}/top", params={"t": "day", "limit": 50}, headers=h, timeout=20).json()
        for c in data["data"]["children"]:
            d = c["data"]
            n += add_item(items, "reddit:" + d["id"], {
                "source": "reddit", "type": "post", "creator": d["author"], "title": d["title"], "views": d["score"],
                "url": "https://reddit.com" + d["permalink"],
                "published_at": iso(dt.datetime.fromtimestamp(d["created_utc"], dt.timezone.utc))})
    return n


UNAVAILABLE = {
    "tiktok": "No official discovery API for our account type (the Research API is for academics). Manual watch only.",
    "instagram": "No public hashtag or creator discovery without a Business app review. Manual watch only.",
    "x": "Search API is paid. Manual watch only.",
    "facebook_gaming": "No official public discovery API. Manual watch only.",
    "discord_communities": "Reading a server needs its admins to add our bot. Manual watch only.",
}


# ------------------------------------------------------------------ intelligence
def prioritise(clips):
    """Metadata-only priority (0-10) that tells the engine what to analyse first. Visual, emotional and replay
    scores come later from the video analysis; storytelling is not measured."""
    repost = re.compile(CFG["repost_name_regex"], re.I)
    for r in clips.values():
        age = age_hours(r.get("created_at"))
        # at least 3 h of age, so a clip with a dozen views in its first minutes does not look viral
        vel = max(r.get("views", 0) / max(age, 3.0), r.get("views_per_hour_recent", 0))
        tops = topics_of(r.get("title"))
        original = not repost.search(r.get("creator", ""))
        french = bool(re.search(r"\b(le|la|les|une|des|wesh|ptdr|mdr|fr[eè]re|c'est|trop)\b", (r.get("title") or "").lower())) \
            or r.get("language") in ("fr", "French")
        s = {"momentum": round(min(10, 4 * math.log10(1 + vel)), 1), "topic_match": min(10, 5 * len(tops)),
             "originality": 8 if original else 2, "french": 10 if french else 3,
             "freshness": round(max(0, 10 - age / 7), 1), "short_enough": 10 if 8 <= r.get("duration", 0) <= 65 else 2}
        w = {"momentum": .4, "topic_match": .15, "originality": .15, "french": .1, "freshness": .1, "short_enough": .1}
        r["radar"] = {**s, "priority": round(sum(s[k] * w[k] for k in w), 2), "topics": tops}
        r["origin"] = "original" if original else "likely_repost"
        if tops:
            r["pillar"], r["pillar_method"] = CFG["topics"][tops[0]]["pillar"], "keyword"


def build_creators(creators, clips, items):
    repost = re.compile(CFG["repost_name_regex"], re.I)
    agg = {}
    for r in list(clips.values()) + list(items.values()):
        if r.get("type") == "article":
            continue
        k = f"{r['source']}:{r['creator']}"
        a = agg.setdefault(k, {"clips": 0, "views": 0, "best_score": 0.0, "posted": 0, "rejected": 0, "first": r.get("discovered_at")})
        a["first"] = min(a["first"] or r.get("discovered_at"), r.get("discovered_at") or a["first"])
        if "duration" in r:
            a["clips"] += 1
            a["views"] += r.get("views", 0)
            a["best_score"] = max(a["best_score"], (r.get("scores") or {}).get("total", 0))
            a["posted"] += r.get("status") in ("posted", "approved")
            a["rejected"] += str(r.get("status", "")).startswith("rejected")
    for k, a in agg.items():
        platform, name = k.split(":", 1)
        creators.setdefault(k, {}).update({
            "platform": platform, "name": name, "clips": a["clips"], "clip_views": a["views"],
            "best_score": a["best_score"], "used": a["posted"], "rejected": a["rejected"], "first_seen": a["first"],
            "origin": "likely_repost" if repost.search(name) else "original"})


def build_topics(clips, items):
    """Creator content (clips, streams, videos) drives the trend; articles are counted apart, since some news
    queries search for one topic and would inflate it."""
    out = {k: {"pillar": v["pillar"], "last_24h": 0, "previous_24h": 0, "news_24h": 0, "examples": []}
           for k, v in CFG["topics"].items()}
    for r in items.values():
        if r.get("type") == "article" and age_hours(r.get("published_at")) <= 24:
            for t in r.get("topics", []):
                out[t]["news_24h"] += 1
    pool = [(r.get("title"), r.get("created_at"), r.get("url")) for r in clips.values()]
    pool += [(r.get("title"), r.get("published_at"), r.get("url")) for r in items.values() if r.get("type") not in ("live_moment", "article")]
    for title, when, url in pool:
        age = age_hours(when)
        if age > 48:
            continue
        for t in topics_of(title):
            out[t]["last_24h" if age <= 24 else "previous_24h"] += 1
            if age <= 24 and len(out[t]["examples"]) < 5:
                out[t]["examples"].append({"title": title, "url": url})
    for t in out.values():
        t["trend"] = round((t["last_24h"] + 1) / (t["previous_24h"] + 1), 2)
    return out


def prune(items, days=7):
    for k in [k for k, r in items.items() if age_hours(r.get("last_seen")) > days * 24]:
        del items[k]


def dashboard(clips, creators, items, topics, runs):
    rows = []
    for r in clips.values():
        rows.append([r.get("type", "clip"), r["source"], r["creator"], r.get("title", ""), r.get("url"),
                     (r.get("radar") or {}).get("priority", 0), r.get("views", 0), r.get("pillar", ""),
                     r.get("status", ""), r.get("origin", ""), r.get("created_at", "")])
    for r in items.values():
        pr = min(10, round(2 * r.get("chat_spike_ratio", 0) + r.get("hype_messages", 0) / 5, 2)) if r["type"] == "live_moment" else 0
        rows.append([r["type"], r["source"], r["creator"], r.get("title", ""), r.get("url"), pr,
                     r.get("viewers", r.get("views", 0)), ", ".join(r.get("topics", [])), "", "", r.get("published_at") or ""])
    rows.sort(key=lambda x: (-x[5], str(x[10])), reverse=False)
    data = {"generated": iso(), "rows": rows[:1500], "status": STATUS, "topics": topics,
            "creators": sorted(creators.values(), key=lambda c: -(c.get("clip_views", 0) + c.get("peak_viewers", 0)))[:300],
            "runs": runs[-24:]}
    tpl = (ROOT / "ops" / "dashboard_template.html").read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    (ROOT / "ops" / "radar_dashboard.html").write_text(tpl.replace("__DATA__", blob), encoding="utf-8")


def main():
    t0 = time.time()
    clips = engine.load_db()
    creators, items = load("creators.json", {}), load("items.json", {})
    n0 = len(clips)
    run_source("kick_clips", kick_clips, clips)
    run_source("kick_live", kick_live, items, creators)
    news(items)
    run_source("youtube_channel_feeds", youtube_feeds, items, creators)
    run_source("twitch", twitch, items)
    run_source("youtube_search", youtube_search, items)
    run_source("reddit", reddit, items)
    for k, why in UNAVAILABLE.items():
        STATUS[k] = {"state": "unavailable", "detail": why, "new": 0}
    engine.mark_used(clips)
    prioritise(clips)
    prune(items)
    build_creators(creators, clips, items)
    topics = build_topics(clips, items)
    runs = load("radar_log.json", [])
    runs.append({"at": iso(), "seconds": round(time.time() - t0), "new_clips": len(clips) - n0, "clips": len(clips),
                 "items": len(items), "creators": len(creators),
                 "sources": {k: v for k, v in STATUS.items() if v["state"] != "unavailable"}})
    runs = runs[-240:]
    engine.save_db(clips)
    save("creators.json", creators)
    save("items.json", items)
    save("topics.json", topics)
    save("radar_log.json", runs)
    dashboard(clips, creators, items, topics, runs)
    print(json.dumps({k: v for k, v in runs[-1].items() if k != "sources"}))
    if not any(v["state"] == "ok" for v in STATUS.values()):
        sys.exit("every source failed")


if __name__ == "__main__":
    main()
