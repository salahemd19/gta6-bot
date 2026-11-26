"""Music step of production: 3 licensed recommendations for a video, plus the usage log so songs don't repeat.

  python music/recommend.py chaos --platform youtube --duration 33 [--energy high]
  python music/recommend.py --use ytal-ego-chall top5-semaine-20261126 --platform youtube
"""
import argparse
import datetime as dt
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = HERE / "library.json"
LOG = HERE / "usage_log.json"
USABLE = {"youtube": {"APPROVED"}, "tiktok": {"APPROVED", "IN_APP_ONLY"}, "reels": {"APPROVED", "IN_APP_ONLY"}}
EFFECT = {"high": "adrenaline, keeps the viewer watching to the next cut", "medium": "momentum without tiring the ear",
          "low": "atmosphere, lets the game sound breathe"}


def load():
    lib = json.loads(LIB.read_text(encoding="utf-8"))
    log = json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else []
    return lib, log


def recommend(category, platform, duration, energy=None, n=3):
    lib, log = load()
    recent = [e["track"] for e in log if e["platform"] == platform][-6:]
    picks = []
    for t in lib["tracks"]:
        if t.get("kind") == "sfx" or t["platforms"].get(platform) not in USABLE[platform]:
            continue
        s = 3 if category in t["categories"] else 0
        s += 1 if energy and t["energy"] == energy else 0
        s -= 4 if t["id"] in recent[-2:] else (2 if t["id"] in recent else 0)   # no back-to-back repeats
        s -= 1 if t.get("duration") and t["duration"] < duration else 0
        if s > 0:
            picks.append((s, t))
    picks.sort(key=lambda x: -x[0])
    out = []
    for s, t in picks[:n]:
        how = ("add it in TikTok Studio > Sons (in-app picker), never in the file" if t["platforms"][platform] == "IN_APP_ONLY"
               else "mix it into the file")
        out.append({"id": t["id"], "track": f'{t["title"]} - {t["artist"]}', "why": f'{t["mood"]}, fits {t["best_moments"]}',
                    "effect": EFFECT.get(t["energy"], ""), "licence": f'{platform}: {t["platforms"][platform]} ({t["source"]})',
                    "attribution": t["attribution"], "start_s": t.get("best_start", 0),
                    "volume_db": t.get("volume_db", -16),
                    "volume_rule": "under voices and game SFX: duck a further -6 dB while someone speaks",
                    "changes": "cut or drop the music on the #1 reveal for 0.5 s, then back in; fade out the last 1.5 s",
                    "how": how})
    return out


def use(track, video, platform):
    _, log = load()
    log.append({"track": track, "video": video, "platform": platform, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")})
    LOG.write_text(json.dumps(log, indent=1), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("category", nargs="?")
    ap.add_argument("--platform", default="youtube", choices=list(USABLE))
    ap.add_argument("--duration", type=float, default=30)
    ap.add_argument("--energy")
    ap.add_argument("--use", nargs=2, metavar=("TRACK_ID", "VIDEO_ID"))
    a = ap.parse_args()
    if a.use:
        use(a.use[0], a.use[1], a.platform)
        print("logged")
    else:
        recs = recommend(a.category, a.platform, a.duration, a.energy)
        if not recs:
            print("No approved track for this platform/category: use the original VICECITY stingers only.")
        for i, r in enumerate(recs):
            print(("BEST " if i == 0 else f"ALT{i} ") + json.dumps(r, ensure_ascii=False))
