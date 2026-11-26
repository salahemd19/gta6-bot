import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
import analytics as A  # noqa: E402
import factory as F  # noqa: E402
import publisher as P  # noqa: E402

UTC = dt.timezone.utc


def item(n, **kw):
    base = {"id": f"v{n}", "title": f"Titre {n}", "rights": "licensed", "category": "A", "youtube": "pending",
            "tiktok": "pending", "sources": [{"content_id": f"c{n}"}], "video_url": "https://x/v.mp4"}
    return {**base, **kw}


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        d = Path(self.dir.name)
        self.old = (P.MANIFEST, P.CALENDAR, P.HISTORY, P.ERRORS, A.METRICS)
        P.MANIFEST, P.CALENDAR, P.HISTORY, P.ERRORS, A.METRICS = (d / n for n in ("m.json", "c.json", "h.jsonl", "e.jsonl", "x.jsonl"))

    def tearDown(self):
        P.MANIFEST, P.CALENDAR, P.HISTORY, P.ERRORS, A.METRICS = self.old
        self.dir.cleanup()


class Publishing(Sandbox):
    now = dt.datetime(2026, 11, 27, 6, 0, tzinfo=UTC)

    def assigned(self, cal, platform="youtube"):
        return [r["id"] for d in cal["platforms"][platform]["days"] for r in d["slots"] if r["status"] == "assigned"]

    def test_only_approved_cleared_unique_items_get_a_slot(self):
        P.save(P.MANIFEST, [item(1), item(2, rights="unverified"), item(3, youtube="awaiting approval"),
                            item(4, factual_issue="false claim"), item(5, sources=[{"content_id": "c1"}]),
                            item(6, authenticity="unresolved"), item(7, hold="check")])
        cal = P.plan(now=self.now)
        self.assertEqual(len([i for i in self.assigned(cal) if i in ("v1", "v5")]), 1)
        self.assertEqual(set(self.assigned(cal)) - {"v1", "v5"}, set())
        self.assertIn("v3", [w["id"] for w in cal["waiting_approval"]])

    def test_slots_follow_paris_time_in_winter_and_summer(self):
        for day, offset in ((dt.date(2027, 1, 15), 1), (dt.date(2027, 7, 15), 2)):
            first = P.slot_times(day, "youtube", 6, P.cfg())[0][0]
            self.assertEqual(first.utcoffset(), dt.timedelta(hours=offset))
            self.assertTrue(dt.time(11, 30) <= first.time() < dt.time(13, 30))

    def test_daily_cap_and_gap(self):
        P.save(P.MANIFEST, [item(n) for n in range(30)])
        cal = P.plan(days=1, now=self.now)
        for p in P.PLATFORMS:
            rows = cal["platforms"][p]["days"][0]["slots"]
            self.assertLessEqual(len(rows), cal["platforms"][p]["cap"])
            times = [dt.datetime.fromisoformat(r["utc"]) for r in rows]
            self.assertTrue(all(b - a >= dt.timedelta(minutes=25) for a, b in zip(times, times[1:])))

    def test_marking_respects_approval_and_retries_then_gives_up(self):
        P.save(P.MANIFEST, [item(1), item(2, youtube="awaiting approval")])
        with self.assertRaises(SystemExit):
            P.mark("v2", "youtube", "posted")
        for _ in range(2):
            self.assertTrue(P.mark("v1", "youtube", "failed", error="x").startswith("failed (retry"))
        self.assertTrue(P.mark("v1", "youtube", "failed", error="x").startswith("failed: "))
        self.assertTrue(P.lines(P.ERRORS))


class Analytics(Sandbox):
    def test_checkpoints_and_no_advice_from_small_samples(self):
        P.save(P.MANIFEST, [])
        A.store([{"platform": "youtube", "key": "a", "title": "t", "published_at": "2026-11-01T10:00:00+00:00",
                  "at": at, "views": v} for at, v in (("2026-11-01T11:10+00:00", 10), ("2026-11-02T10:00+00:00", 500))])
        x = A.publications()[0]
        self.assertEqual(x["checkpoints"]["1h"]["views"], 10)
        self.assertEqual(A.value(x), 500)
        self.assertNotIn("7d", x["checkpoints"])
        self.assertEqual(A.advice(A.compare([x]), [x])[0]["level"], "wait")


class Factory(unittest.TestCase):
    ok = {"content_id": "c", "rights": "licensed", "state": "active", "authenticity": "verified_by_review", "used_in": []}
    review = {"verdict": "keep", "action_fr": "x", "hooks_fr": ["a", "b", "c"]}

    def test_gate(self):
        self.assertEqual(F.blockers(self.ok, self.review, set()), [])
        for bad in ({"rights": "unverified"}, {"authenticity": "not_gta6"}, {"used_in": ["v"]}, {"state": "rejected"}):
            self.assertTrue(F.blockers({**self.ok, **bad}, self.review, set()), bad)
        self.assertTrue(F.blockers(self.ok, None, set()))

    def test_subtitle_chunks_cover_the_line_without_overlap(self):
        c = F.chunks("un deux trois quatre cinq six sept huit neuf", 1.0, 4.0)
        self.assertEqual((c[0][0], c[-1][1]), (1.0, 4.0))
        self.assertTrue(all(a[1] <= b[0] + 0.01 for a, b in zip(c, c[1:])))

    def test_every_template_resolves(self):
        for name in F.CFG["templates"]:
            self.assertTrue({"badge", "accent", "music", "cta", "grade", "zoom", "flash"} <= set(F.template(name)))


if __name__ == "__main__":
    unittest.main()
