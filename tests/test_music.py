import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "music"))
import recommend as R  # noqa: E402


def track(i, state="IN_APP_ONLY"):
    return {"id": i, "title": i, "artist": "a", "categories": ["chaos"], "energy": "high", "mood": "m", "best_moments": "b",
            "platforms": {"tiktok": state}, "source": "s", "attribution": "none"}


class Rotation(unittest.TestCase):
    def setUp(self):
        self.old = R.load
        self.addCleanup(setattr, R, "load", self.old)

    def library(self, tracks, used):
        R.load = lambda: ({"tracks": tracks}, [{"track": t, "platform": "tiktok"} for t in used])

    def test_small_library_alternates_instead_of_running_out(self):
        self.library([track("a"), track("b")], ["a", "b"])
        self.assertEqual([r["id"] for r in R.recommend("chaos", "tiktok", 20)], ["a"])
        self.library([track("a"), track("b")], ["b", "a"])
        self.assertEqual([r["id"] for r in R.recommend("chaos", "tiktok", 20)], ["b"])

    def test_unapproved_track_is_never_offered_and_one_track_is_not_repeated(self):
        self.library([track("a"), track("x", "NOT_APPROVED")], ["a"])
        self.assertEqual(R.recommend("chaos", "tiktok", 20), [])


if __name__ == "__main__":
    unittest.main()
