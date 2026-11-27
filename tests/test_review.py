import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
import factory as F  # noqa: E402
import review as R  # noqa: E402


def rec(cid="VCI-x", **kw):
    return {"content_id": cid, "duration": 30, "state": "active", "used_in": [], "creator": "c", "rights": "licensed", **kw}


GOOD = {"verdict": "keep", "action_fr": "Une voiture saute.", "hooks_fr": ["A", "B", "C"], "category": "RACING & VEHICLES",
        "strength": 7, "window": [2, 12]}


class Verdicts(unittest.TestCase):
    def test_complete_keep_and_reasoned_reject_pass(self):
        self.assertIsNone(R.problems("VCI-x", GOOD, rec()))
        self.assertIsNone(R.problems("VCI-x", {"verdict": "reject", "reason": "menu"}, rec()))

    def test_incomplete_or_unavailable_is_refused(self):
        for change in ({"hooks_fr": ["A"]}, {"category": "x"}, {"window": [0, 2]}, {"window": [0, 99]}, {"action_fr": " "},
                       {"strength": 11}, {"verdict": "maybe"}):
            self.assertIsNotNone(R.problems("VCI-x", {**GOOD, **change}, rec()), change)
        self.assertIsNotNone(R.problems("VCI-x", GOOD, rec(state="rejected")))
        self.assertIsNotNone(R.problems("VCI-x", GOOD, rec(used_in=["v"])))
        self.assertIsNotNone(R.problems("VCI-x", {"verdict": "reject"}, rec()))
        self.assertIsNotNone(R.problems("VCI-y", GOOD, None))


class Candidates(unittest.TestCase):
    def test_mature_flag_does_not_empty_the_queue_and_one_clip_per_creator(self):
        db = {n: {"content_id": f"VCI-{n}", "status": "analysed", "media_url": "u", "state": "active", "rights": "licensed",
                  "creator": "a" if n < 2 else "b", "is_mature": True} for n in range(3)}
        self.assertEqual([r["creator"] for r in R.candidates(db, {"VCI-9": {}}, 12)], ["a", "b"])


class Category(unittest.TestCase):
    def test_reviewed_category_survives_the_next_sync(self):
        import contentdb as c
        r = {"id": "x", "url": "https://kick.com/a/clips/x", "creator": "a", "source": "kick", "pillar": "MAP", "title": "t",
             "category": "RACING & VEHICLES", "category_reviewed": True, "status": "analysed", "duration": 10}
        c.ensure_model(r)
        self.assertEqual(r["category"], "RACING & VEHICLES")


class Order(unittest.TestCase):
    def test_strongest_closes_and_second_opens(self):
        picks = [{"id": "a", "strength": 5}, {"id": "b", "strength": 9}, {"id": "c", "strength": 7}]
        self.assertEqual([p["id"] for p in F.countdown(picks)], ["c", "a", "b"])


if __name__ == "__main__":
    unittest.main()
