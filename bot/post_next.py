"""Post the next due video(s) from queue/manifest.json to YouTube and TikTok (runs in GitHub Actions every 2 hours).

Rules: at most 1 post per platform per run; rolling 24 h caps (YouTube 8, TikTok 12); rights gate (owned/licensed/permission_granted only); a platform that errors is
marked 'failed: ...' and retried on the next run (max 3 attempts); nothing is deleted.
"""
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
import approvals
import tiktok
import yt

MANIFEST = Path("queue/manifest.json")
CAPS = {"youtube": 8, "tiktok": 12}  # daily targets (rolling 24 h); quality and rights come first
# Rights gate: only these statuses may ever be published. Anything else (unverified, unresolved, refused) stays queued.
PUBLISHABLE_RIGHTS = {"owned", "licensed", "permission_granted"}
# Platforms the cloud may post to (repo variable CLOUD_PLATFORMS, e.g. "youtube,tiktok"), switched on once the
# YouTube audit / TikTok app review pass. Until then the laptop task posts the approved clips.
ENABLED = {p.strip() for p in os.environ.get("CLOUD_PLATFORMS", "").split(",") if p.strip()}
# Hot windows, Paris time: posts only go out when the French audience is online.
# Testing hypotheses (26 Nov 2026), to be re-ranked from our own analytics. zoneinfo handles CET/CEST.
HOT = {
    "youtube": [((11, 30), (13, 30)), ((14, 30), (15, 45)), ((18, 0), (22, 30))],
    "tiktok": [((11, 30), (13, 30)), ((14, 30), (15, 45)), ((16, 0), (18, 0)), ((18, 0), (22, 30))],
}


def hot_now(platform="tiktok"):
    from zoneinfo import ZoneInfo
    t = dt.datetime.now(ZoneInfo("Europe/Paris"))
    m = t.hour * 60 + t.minute
    return any(a[0] * 60 + a[1] <= m < b[0] * 60 + b[1] for a, b in HOT[platform])


def rights_ok(it):
    return it.get("rights", "unverified") in PUBLISHABLE_RIGHTS


def sync_approvals(items):
    """Apply the owner's decisions from GitHub Issues: approved -> pending (postable), rejected -> rejected."""
    try:
        dec = approvals.decisions()
    except Exception as e:  # noqa: BLE001
        print("::warning::approvals unavailable:", e)
        return False
    changed = False
    for it in items:
        d = dec.get(it.get("issue"))
        for p in ("youtube", "tiktok"):
            if str(it.get(p, "")).startswith("awaiting approval") and d:
                it[p] = "pending" if d == "approved" else "rejected by owner"
                changed = True
        if d == "approved" and it.get("slot", "") > now().isoformat():
            it["slot"] = now().isoformat(timespec="seconds")
    return changed


def now():
    return dt.datetime.now(dt.timezone.utc)


def posted_last_24h(items, platform):
    n = 0
    for it in items:
        s = str(it.get(platform, ""))
        if s.startswith("posted "):
            try:
                if now() - dt.datetime.fromisoformat(s[7:]) < dt.timedelta(hours=24):
                    n += 1
            except ValueError:
                pass
    return n


def due(it, platform):
    s = str(it.get(platform, "pending"))
    if not (s.startswith("pending") or s.startswith("failed (retry")):
        return False
    return dt.datetime.fromisoformat(it["slot"]) <= now()  # slots are UTC ISO strings


def fetch(it, tmp):
    p = Path(tmp) / (it["id"] + ".mp4")
    with requests.get(it["video_url"], stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(p, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return p


def main():
    items = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ts = now().isoformat(timespec="minutes")
    changed = sync_approvals(items)
    for platform in ("youtube", "tiktok"):
        if platform not in ENABLED:
            continue
        if not hot_now(platform):
            print(platform, "outside the hot windows; nothing posted")
            continue
        if posted_last_24h(items, platform) >= CAPS[platform]:
            print(platform, "cap reached; skipping")
            continue
        blocked = [i["id"] for i in items if due(i, platform) and not rights_ok(i)]
        if blocked:
            print(platform, "held by the rights gate:", blocked[:5])
        cands = sorted((i for i in items if due(i, platform) and rights_ok(i)), key=lambda i: -i.get("score", 0))
        if not cands:
            print(platform, "nothing due")
            continue
        it = cands[0]
        with tempfile.TemporaryDirectory() as tmp:
            try:
                path = fetch(it, tmp)
                if platform == "youtube":
                    vid = yt.upload(path, it["title"], it["youtube_description"], it.get("youtube_privacy", "public"))
                    it["youtube"] = f"posted {ts}"
                    it["youtube_url"] = f"https://youtube.com/shorts/{vid}"
                else:
                    pid, status, new_refresh = tiktok.post(path, it["tiktok_caption"])
                    it["tiktok"] = f"posted {ts}" if status == "PUBLISH_COMPLETE" else f"posted {ts} (status {status})"
                    if new_refresh and new_refresh != os.environ.get("TIKTOK_REFRESH_TOKEN"):
                        print("::warning::TikTok rotated the refresh token; update the TIKTOK_REFRESH_TOKEN secret")
                print("posted", it["id"], "to", platform)
                if it.get("issue"):
                    approvals.mark_posted(it["issue"], [it.get("youtube_url", "")] if platform == "youtube" else ["TikTok"])
            except Exception as e:  # noqa: BLE001 - one bad post must not stop the other platform
                tries = it.get(platform + "_tries", 0) + 1
                it[platform + "_tries"] = tries
                it[platform] = f"failed (retry {tries}/3): {str(e)[:120]}" if tries < 3 else f"failed: {str(e)[:120]}"
                print("::error::", platform, it["id"], e)
        changed = True
    if changed:
        MANIFEST.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
