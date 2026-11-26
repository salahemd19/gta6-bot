"""Chat reaction signal from Kick's public chat history (read-only), used to find the moments the audience reacted to.

  fetch(slug, start_epoch, seconds) -> {"start": epoch, "offsets": [seconds from capture start, ...], "hype": [offsets of laugh/hype messages]}
The history endpoint returns one ~5 s window per call, so a 10 min capture needs ~120 calls (done in parallel).
"""
import datetime as dt
import re
import warnings
from concurrent.futures import ThreadPoolExecutor

import requests

warnings.filterwarnings("ignore")
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
HYPE = re.compile(r"(kekw|mdr|ptdr|lol|omg|wtf|\bgg\b|poggers|pog|ahah|haha|😂|🤣|💀|😱|🔥|incroyable|cringe|dinguerie|la folie|ouf|banger|clip)", re.I)


def channel_id(slug):
    return requests.get(f"https://kick.com/api/v1/channels/{slug}", headers=H, verify=False, timeout=20).json()["id"]


def _window(args):
    ch, st = args
    s = dt.datetime.fromtimestamp(st, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    try:
        r = requests.get(f"https://kick.com/api/v2/channels/{ch}/messages?start_time={s}", headers=H, verify=False, timeout=20).json()
        return r["data"]["messages"]
    except Exception:
        return []


def fetch(slug, start_epoch, seconds, ch=None):
    ch = ch or channel_id(slug)
    steps = [(ch, start_epoch + i) for i in range(0, int(seconds) + 5, 5)]
    seen, offsets, hype = set(), [], []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for msgs in ex.map(_window, steps):
            for m in msgs:
                if m["id"] in seen:
                    continue
                seen.add(m["id"])
                t = dt.datetime.fromisoformat(m["created_at"].replace("Z", "+00:00")).timestamp() - start_epoch
                if 0 <= t <= seconds:
                    offsets.append(round(t, 1))
                    if HYPE.search(m.get("content", "")):
                        hype.append(round(t, 1))
    return {"start": start_epoch, "offsets": sorted(offsets), "hype": sorted(hype), "channel": ch}


def window_boost(chat, start, end, lag=3.0):
    """Score bonus for a clip window: chat activity (and laugh/hype messages) vs the stream's own average rate."""
    if not chat or not chat.get("offsets"):
        return 0.0
    total = max(chat["offsets"][-1], 60.0)
    avg = len(chat["offsets"]) / total  # messages per second over the capture
    # chat reacts ~lag seconds after the event, so look slightly later than the clip window
    n = sum(1 for t in chat["offsets"] if start + lag <= t <= end + lag)
    h = sum(1 for t in chat["hype"] if start + lag <= t <= end + lag)
    rate = n / max(end - start, 1.0)
    ratio = rate / (avg + 1e-6)
    return round(0.5 * min(max(ratio - 1.0, 0.0), 2.0) + 0.08 * min(h, 10), 3)


def spike_windows(chat, length, count=4):
    """Windows centred on the biggest chat spikes: [(start, end, 0.0)] for use as extra candidates."""
    if not chat or len(chat["offsets"]) < 20:
        return []
    import numpy as np
    total = int(chat["offsets"][-1]) + 1
    bins = np.zeros(total + 1)
    for t in chat["offsets"]:
        bins[int(t)] += 1
    k = 10
    sm = np.convolve(bins, np.ones(k), mode="same")
    picks, taken = [], np.zeros(len(sm), bool)
    for i in np.argsort(sm)[::-1]:
        if taken[i]:
            continue
        start = max(0.0, i - 12.0)  # the reaction follows the event: open ~12 s before the spike centre
        picks.append((start, start + length, 0.0))
        taken[max(0, i - int(length)): i + int(length)] = True
        if len(picks) == count:
            break
    return picks
