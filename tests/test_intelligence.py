import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
import intelligence as I  # noqa: E402


def rec(views=0):
    return {"content_id": "VCI-test", "creator": "demo", "platform": "kick", "views": views, "category": "RACING & VEHICLES",
            "analysis": {"start": 2.0, "end": 12.0, "duration": 10.0, "flags": [], "peaks_s": [4.0, 9.0], "scene_changes_s": [],
                         "speech": None, "source": {"height": 1080, "fps": 60, "kbps": 6000},
                         "window": {"motion": 20, "excitement": .6, "variation": .2, "burst": .4, "brightness": 90,
                                    "sharpness": 200, "dead_share": 0, "build": .1},
                         "opening": {"motion": 20, "loud": .7, "excitement": .6}}}


class Scoring(unittest.TestCase):
    def test_unassessed_criteria_are_left_out_not_guessed(self):
        s = I.score(rec())
        self.assertIsNone(s["originality"])
        self.assertEqual(s["method"]["storytelling"], "not_assessed")
        self.assertLess(s["coverage"], 1)
        self.assertTrue(0 <= s["total"] <= 10)

    def test_views_cannot_dominate(self):
        self.assertLess(I.score(rec(10_000_000))["total"] - I.score(rec(0))["total"], 0.3)

    def test_rejected_review_caps_score(self):
        self.assertLessEqual(I.score(rec(), {"verdict": "reject"})["total"], 3)

    def test_brief_flags_unwatched_footage(self):
        b = I.brief(rec())
        self.assertEqual(len(b["hooks"]), 3)
        self.assertEqual(b["series"], "LE BANC D'ESSAI")
        self.assertIsNotNone(b["needs_review"])
        self.assertIsNone(I.brief(rec(), {"action_fr": "Une voiture saute.", "hooks_fr": ["A", "B", "C"]})["needs_review"])

    def test_best_window_avoids_dead_start(self):
        import numpy as np
        ex = np.r_[np.zeros(40), np.ones(40), np.zeros(40)]
        start, end = I.best_window(ex, (ex == 0).astype(float))
        self.assertTrue(8 <= start <= 12 and end <= 22)


if __name__ == "__main__":
    unittest.main()
