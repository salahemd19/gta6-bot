"""Posting from the cloud through Buffer's official API, so the laptop is not needed.

  python cloud/buffer_post.py check      show which channels the key can reach
  python cloud/buffer_post.py run        schedule approved videos and confirm the ones whose time has passed
Env: BUFFER_API_KEY. Posting starts only when config/publishing.json has "poster": "buffer". Only videos with music
mixed into the file are sent (Buffer cannot add platform sounds). Built from developers.buffer.com; not yet run against
a real account.
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publisher as P  # noqa: E402

API = "https://api.buffer.com"
CREATE = ("mutation Create($input: CreatePostInput!) { createPost(input: $input) { __typename "
          "... on PostActionSuccess { post { id } } ... on MutationError { message } } }")
UTC = dt.timezone.utc


def configured():
    return bool(os.environ.get("BUFFER_API_KEY"))


def gql(query, variables=None):
    r = requests.post(API, json={"query": query, "variables": variables or {}}, timeout=90,
                      headers={"Authorization": f"Bearer {os.environ['BUFFER_API_KEY'].strip()}"})
    if r.status_code == 429:
        raise RuntimeError("Buffer rate limit reached")
    try:
        body = r.json()
    except ValueError:
        raise RuntimeError(f"Buffer answered {r.status_code} without JSON") from None
    if body.get("errors") or r.status_code >= 400:
        raise RuntimeError(f"Buffer {r.status_code}: {str((body.get('errors') or [{}])[0].get('message'))[:200]}")
    return body["data"]


def channels():
    """{platform: channel id} for the connected YouTube and TikTok channels."""
    found = {}
    for org in gql("query { account { organizations { id } } }")["account"]["organizations"]:
        data = gql("query { channels(input: { organizationId: %s }) { id name service isDisconnected } }" % json.dumps(org["id"]))
        for c in data["channels"]:
            service = str(c.get("service", "")).lower()
            if service in P.PLATFORMS and not c.get("isDisconnected"):
                found.setdefault(service, c["id"])
    return found


def baked(item, platform):
    return ((item.get("music") or {}).get(platform) or {}).get("mode") == "mixed into file"


def eligible(item, platform, done, now):
    slot = P.when(item.get(f"slot_{platform}"))
    return bool(P.kind(item.get(platform)) == "ready" and not P.gate(item) and slot and slot > now + dt.timedelta(minutes=3)
                and baked(item, platform) and not item.get(f"{platform}_buffer_id") and not P.clashes(item, done)
                and P.package(item, platform).get("video_url"))


def post_input(item, platform, channel):
    pack = P.package(item, platform)
    due = P.when(item[f"slot_{platform}"]).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    data = {"channelId": channel, "schedulingType": "automatic", "mode": "customScheduled", "dueAt": due,
            "text": pack.get("description") if platform == "youtube" else pack.get("caption"),
            "assets": [{"video": {"url": pack["video_url"]}}]}
    if platform == "youtube":
        data["metadata"] = {"youtube": {"title": pack["title"][:100], "categoryId": "20", "madeForKids": False}}
    return data


def create(data):
    try:
        result = gql(CREATE, {"input": data})["createPost"]
    except RuntimeError as e:
        if "needsApproval" not in str(e):  # the published schema and examples disagree about this field
            raise
        result = gql(CREATE, {"input": {**data, "needsApproval": False}})["createPost"]
    if result.get("__typename") != "PostActionSuccess":
        raise RuntimeError(f"{result.get('__typename')}: {result.get('message')}")
    return result["post"]["id"]


def remember(item_id, platform, post_id):
    items = P.load(P.MANIFEST, [])
    next(i for i in items if i["id"] == item_id)[f"{platform}_buffer_id"] = post_id
    P.save(P.MANIFEST, items)


def schedule(found, now):
    items = P.load(P.MANIFEST, [])
    done = {p: [i for i in items if P.kind(i.get(p)) in P.DONE] for p in P.PLATFORMS}
    sent, failed = [], []
    todo = sorted(((i[f"slot_{p}"], i["id"], p) for i in items for p in found if eligible(i, p, done[p], now)))
    for _, item_id, p in todo[:20]:
        item = next(i for i in P.load(P.MANIFEST, []) if i["id"] == item_id)
        if P.clashes(item, done[p]):
            continue
        try:
            post_id = create(post_input(item, p, found[p]))
        except (RuntimeError, requests.RequestException) as e:
            P.mark(item_id, p, "failed", error=str(e))
            failed.append(f"{item_id} {p}: {str(e)[:80]}")
            continue
        remember(item_id, p, post_id)  # first, so a later error can never cause a second upload
        P.mark(item_id, p, "scheduled", at=item[f"slot_{p}"])
        done[p].append(item)
        sent.append(f"{item_id} {p}")
    return sent, failed


def post_status(post_id):
    query = "query { post(input: { id: %s }) { id status %s } }"
    try:
        return gql(query % (json.dumps(post_id), "externalLink"))["post"]
    except RuntimeError:
        return gql(query % (json.dumps(post_id), ""))["post"]


def verify(now):
    done = []
    for item in P.load(P.MANIFEST, []):
        for p in P.PLATFORMS:
            t = P.when(item.get(p))
            if not (item.get(f"{p}_buffer_id") and P.kind(item.get(p)) == "scheduled" and t and now - t > dt.timedelta(minutes=10)):
                continue
            post = post_status(item[f"{p}_buffer_id"])
            state = str(post.get("status", "")).lower()
            if state == "sent":
                P.mark(item["id"], p, "posted", url=post.get("externalLink"), at=t.isoformat(timespec="minutes"))
                done.append(f"{item['id']} {p} posted")
            elif state == "error":
                items = P.load(P.MANIFEST, [])
                next(i for i in items if i["id"] == item["id"]).pop(f"{p}_buffer_id", None)
                P.save(P.MANIFEST, items)
                P.mark(item["id"], p, "failed", error="Buffer reports a publishing error")
                done.append(f"{item['id']} {p} failed")
    return done


def run(now=None):
    if not configured():
        return "not connected (add the secret BUFFER_API_KEY)"
    now = now or dt.datetime.now(UTC)
    found = channels()
    names = ", ".join(sorted(found)) or "none"
    if P.cfg().get("poster") != "buffer":
        return f"key works, channels connected: {names}; set \"poster\": \"buffer\" in config/publishing.json to start"
    checked = verify(now)
    if P.load(P.ROOT / "config" / "overrides.json", {}).get("paused"):
        return f"paused; confirmed: {checked or 'nothing'}"
    sent, failed = schedule(found, now)
    if failed:
        raise RuntimeError("; ".join(failed)[:300])
    missing = [p for p in P.PLATFORMS if p not in found]
    return f"scheduled {sent or 'nothing'}; confirmed {checked or 'nothing'}" + (f"; channel missing: {missing}" if missing else "")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "run"])
    a = ap.parse_args()
    print(channels() if a.cmd == "check" else run())


if __name__ == "__main__":
    main()
