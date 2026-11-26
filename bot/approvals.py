"""Human approval gate on GitHub Issues (works from the GitHub phone app).

Each new clip opens an issue labelled `a-valider`. The owner adds the label `approved` to publish it, or `rejected`
(or simply closes the issue) to drop it. Only approved clips are ever posted.
"""
import os

import requests

REPO = os.environ.get("GITHUB_REPOSITORY", "salahemd19/gta6-bot")
API = f"https://api.github.com/repos/{REPO}"
LABELS = {"a-valider": "FBCA04", "approved": "0E8A16", "rejected": "B60205", "posted": "1D76DB"}


def _h():
    return {"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"}


def ensure_labels():
    for name, color in LABELS.items():
        requests.post(f"{API}/labels", headers=_h(), json={"name": name, "color": color}, timeout=30)


def open_issue(entry):
    body = (f"**{entry['title']}**\n\n"
            f"Vidéo : {entry['video_url']}\n\n"
            f"Streamer : {entry.get('streamer', '?')} · score {entry.get('score')} · mouvement {entry.get('motion')}\n\n"
            "Pour publier : ajoute le label **approved**. Pour rejeter : label **rejected** ou ferme l'issue.")
    r = requests.post(f"{API}/issues", headers=_h(), timeout=30,
                      json={"title": f"À valider : {entry['title']}", "body": body, "labels": ["a-valider"]})
    r.raise_for_status()
    return r.json()["number"]


def decisions():
    """{issue_number: 'approved' | 'rejected'} for every decided clip issue."""
    out = {}
    for state in ("open", "closed"):
        page = 1
        while True:
            r = requests.get(f"{API}/issues", headers=_h(), timeout=30,
                             params={"state": state, "labels": "a-valider", "per_page": 100, "page": page})
            r.raise_for_status()
            batch = r.json()
            for i in batch:
                names = {l["name"] for l in i["labels"]}
                if "rejected" in names or (state == "closed" and "approved" not in names and "posted" not in names):
                    out[i["number"]] = "rejected"
                elif "approved" in names:
                    out[i["number"]] = "approved"
            if len(batch) < 100:
                break
            page += 1
    return out


def mark_posted(number, links):
    requests.post(f"{API}/issues/{number}/comments", headers=_h(), timeout=30,
                  json={"body": "Publié : " + " · ".join(links)})
    requests.post(f"{API}/issues/{number}/labels", headers=_h(), json={"labels": ["posted"]}, timeout=30)
