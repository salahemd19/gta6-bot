import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "cloud"), str(REPO / "music")]
import analytics as A  # noqa: E402
import buffer_post as B  # noqa: E402
import publisher as P  # noqa: E402
import recommend as R  # noqa: E402
import review as V  # noqa: E402

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 28, 9, 0, tzinfo=UTC)
MIXED = {"mode": "mixed into file", "id": "vci-drift"}


def item(n, **kw):
    base = {"id": f"v{n}", "title": f"Titre {n}", "rights": "licensed", "sources": [{"content_id": f"c{n}"}],
            "video_url": "https://x/v.mp4", "youtube_description": "d", "tiktok_caption": "c",
            "youtube": "pending", "tiktok": "pending", "slot_youtube": "2026-11-28T11:00+00:00",
            "slot_tiktok": "2026-11-28T12:00+00:00", "music": {"youtube": MIXED, "tiktok": MIXED}}
    return {**base, **kw}


class Sandbox(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        self.keep(P, "MANIFEST", "CALENDAR", "HISTORY", "ERRORS", "cfg")
        P.MANIFEST, P.CALENDAR, P.HISTORY, P.ERRORS = (d / n for n in ("m.json", "c.json", "h.jsonl", "e.jsonl"))
        real = P.cfg()
        P.cfg = lambda: {**real, "poster": "buffer"}

    def keep(self, module, *names):
        for n in names:
            self.addCleanup(setattr, module, n, getattr(module, n))

    def get(self, n=1):
        return next(i for i in P.load(P.MANIFEST, []) if i["id"] == f"v{n}")


class Buffer(Sandbox):
    def setUp(self):
        super().setUp()
        self.keep(B, "gql", "channels")
        self.sent = []
        B.channels = lambda: {"youtube": "Y", "tiktok": "T"}

        def gql(query, variables=None):
            if "createPost" in query:
                self.sent.append(variables["input"])
                return {"createPost": {"__typename": "PostActionSuccess", "post": {"id": f"p{len(self.sent)}"}}}
            return {"post": {"id": "p", "status": "sent", "externalLink": "https://x/post"}}
        B.gql = gql
        old = os.environ.get("BUFFER_API_KEY")
        os.environ["BUFFER_API_KEY"] = "test"
        self.addCleanup(lambda: os.environ.pop("BUFFER_API_KEY") if old is None else os.environ.update(BUFFER_API_KEY=old))

    def test_only_approved_videos_with_baked_music_are_sent_once(self):
        P.save(P.MANIFEST, [item(1), item(2, youtube="awaiting approval", tiktok="awaiting approval"),
                            item(3, music={"youtube": {"mode": "add in the YouTube Studio editor"}}),
                            item(4, rights="unverified")])
        B.run(NOW)
        self.assertEqual(sorted(s["channelId"] for s in self.sent), ["T", "Y"])
        self.assertEqual(self.sent[0]["metadata"]["youtube"]["categoryId"], "20")
        self.assertEqual(self.sent[0]["dueAt"], "2026-11-28T11:00:00.000Z")
        self.assertTrue(self.get()["youtube"].startswith("scheduled"))
        B.run(NOW)
        self.assertEqual(len(self.sent), 2)

    def test_confirmation_after_the_slot(self):
        P.save(P.MANIFEST, [item(1)])
        B.run(NOW)
        B.run(NOW + dt.timedelta(hours=5))
        self.assertTrue(self.get()["tiktok"].startswith("posted"))
        self.assertEqual(self.get()["youtube_url"], "https://x/post")

    def test_refusal_is_recorded_for_retry(self):
        B.gql = lambda q, v=None: {"createPost": {"__typename": "LimitReachedError", "message": "full"}}
        P.save(P.MANIFEST, [item(1, tiktok="rejected by owner")])
        with self.assertRaises(RuntimeError):
            B.run(NOW)
        self.assertTrue(self.get()["youtube"].startswith("failed (retry 1/3)"))


class YouTubeCheck(Sandbox):
    def test_public_video_is_marked_posted(self):
        self.keep(A, "youtube_get")
        A.youtube_get = lambda path, **kw: {"items": [{"id": "abcdefghijk", "status": {"privacyStatus": "public"}},
                                                      {"id": "zzzzzzzzzzz", "status": {"privacyStatus": "private"}}]}
        P.save(P.MANIFEST, [item(1, youtube="scheduled 2026-11-28T08:00+00:00", youtube_url="https://youtube.com/shorts/abcdefghijk"),
                            item(2, youtube="scheduled 2026-11-28T06:00+00:00", youtube_url="https://youtu.be/zzzzzzzzzzz")])
        out = A.verify_youtube(NOW)
        self.assertTrue(self.get(1)["youtube"].startswith("posted"))
        self.assertTrue(self.get(2)["youtube"].startswith("scheduled"))
        self.assertIn("v2", out)


class Music(unittest.TestCase):
    def test_originals_only_when_music_is_mixed_in_the_cloud(self):
        for platform in ("youtube", "tiktok"):
            for cat in ("racing", "chaos", "secrets", "tips", "challenges", "leonida"):
                baked = [r["id"] for r in R.recommend(cat, platform, 20, baked=True)]
                self.assertTrue(baked and all(i.startswith("vci-") for i in baked), (platform, cat, baked))
                self.assertFalse([r["id"] for r in R.recommend(cat, platform, 20) if r["id"] in
                                  ("vci-drift", "vci-heist", "vci-night-drive")])
        for track in ("vci-drift", "vci-heist", "vci-night-drive"):
            self.assertTrue((REPO / "music" / "original" / f"{track}.mp3").stat().st_size > 200_000)


class Sheets(unittest.TestCase):
    def test_block_has_a_fixed_even_size(self):
        with tempfile.TemporaryDirectory() as d:
            clip, out = Path(d) / "c.mp4", Path(d) / "b.jpg"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x480:rate=10", "-t", "8", str(clip)],
                           check=True)
            self.assertTrue(V.block(clip, 8.0, out))
            size = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
                                  capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(size, "1944,290")


class ReviewExchange(unittest.TestCase):
    def test_queue_branch_is_replaced_and_verdicts_are_read_back(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            d = Path(d)

            def git(where, *a):
                return subprocess.run(["git", *a], cwd=where, check=True, capture_output=True, text=True).stdout
            git(d, "init", "--bare", "-b", "main", "server.git")
            git(d, "clone", "server.git", "work")
            work = d / "work"
            for k, v in (("user.name", "t"), ("user.email", "t@example.invalid")):
                git(work, "config", k, v)
            (work / "a.txt").write_text("a")
            git(work, "add", "-A")
            git(work, "commit", "-m", "a")
            git(work, "push", "-u", "origin", "main")
            sheet = work / "sheet1.jpg"
            sheet.write_bytes(b"\xff\xd8\xff\xd9")
            old = (V.ROOT, V.queue, V.apply, V.contentdb.load, V.intelligence.reviews, V.factory.index)
            self.addCleanup(lambda: (setattr(V, "ROOT", old[0]), setattr(V, "queue", old[1]), setattr(V, "apply", old[2]),
                                     setattr(V.contentdb, "load", old[3]), setattr(V.intelligence, "reviews", old[4]),
                                     setattr(V.factory, "index", old[5])))
            V.ROOT = work
            for n in (1, 2):
                sheet.write_bytes(b"\xff\xd8\xff\xd9")
                V.queue = lambda count: {"folder": str(work), "sheets": [str(sheet)], "clips": [{"id": "VCI-a"}], "ready": 0}
                self.assertIn("published 1", V.publish(1))
            self.assertEqual(len(git(d / "server.git", "log", "--format=%H", "review-queue").split()), 1)
            self.assertIn("queue.json", git(d / "server.git", "ls-tree", "--name-only", "review-queue"))
            self.assertEqual((work / "a.txt").read_text(), "a")
            self.assertIn("no verdicts", V.apply_remote())
            git(work, "checkout", "-q", "-b", "claude/review-verdicts")
            (work / "verdicts").mkdir()
            (work / "verdicts" / "latest.json").write_text(json.dumps(
                {"VCI-a": {"verdict": "reject", "reason": "x"}, "VCI-old": {"verdict": "reject", "reason": "x"},
                 "VCI-unknown": {"verdict": "reject", "reason": "x"}}))
            git(work, "add", "verdicts")
            git(work, "commit", "-q", "-m", "v")
            git(work, "push", "-q", "origin", "claude/review-verdicts")
            seen = {}
            V.contentdb.load = lambda: {}
            V.intelligence.reviews = lambda: {"VCI-old": {}}
            V.factory.index = lambda db: {"VCI-a": {"status": "analysed"}, "VCI-old": {"status": "analysed"}}
            V.apply = lambda new, who: (seen.update(new) or list(new), {})
            self.assertIn("1 verdicts recorded", V.apply_remote())
            self.assertEqual(list(seen), ["VCI-a"])


if __name__ == "__main__":
    unittest.main()
