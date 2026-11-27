"""The one way to save shared data, from the cloud and from the laptop.

  python cloud/save.py "message" queue db [more paths]

Commits those paths, then pulls and pushes with the field-level merge driver, retrying when someone else pushed first.
"""
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git(*args, check=False):
    r = subprocess.run(["git", "-c", "core.longpaths=true", *args], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode:
        raise SystemExit(f"git {args[0]} failed: {r.stderr[-400:]}")
    return r


def configure():
    git("config", "merge.vci.name", "VICECITY data merge", check=True)
    git("config", "merge.vci.driver", f'"{Path(sys.executable).as_posix()}" cloud/mergedb.py %O %A %B %P', check=True)


def save(message, paths, tries=6):
    configure()
    paths = [p for p in paths if (ROOT / p).exists()]
    if paths:
        git("add", "--", *paths, check=True)
    if git("diff", "--cached", "--quiet").returncode:
        git("commit", "-m", message, check=True)
    for n in range(tries):
        pulled = git("pull", "--rebase", "--autostash")
        if pulled.returncode:
            git("rebase", "--abort")
        elif not git("push").returncode:
            return "saved"
        print(f"retry {n + 1}: {(pulled.stderr or 'push refused')[-200:]}")
        time.sleep(random.uniform(3, 10))
    raise SystemExit("could not save after retries; the commit stays local")


if __name__ == "__main__":
    configure() if len(sys.argv) < 2 else print(save(sys.argv[1], sys.argv[2:]))
