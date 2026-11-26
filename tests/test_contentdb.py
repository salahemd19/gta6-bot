import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
import contentdb as c  # noqa: E402


class ContentDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        c.ROOT = Path(self.tmp.name)
        self.db = {}
        self.r, _ = c.add(self.db, {"source": "kick", "id": "a1", "creator": "demo", "url": "https://kick.com/demo/clips/a1"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_duplicates_refused(self):
        _, made = c.add(self.db, {"source": "kick", "id": "a1", "creator": "demo", "url": "x"})
        self.assertFalse(made)
        _, made = c.add(self.db, {"source": "kick", "id": "b2", "creator": "z", "url": "https://www.kick.com/demo/clips/a1?x=1"})
        self.assertFalse(made)
        self.assertEqual(len(self.db), 1)

    def test_no_stage_jump_and_gates(self):
        with self.assertRaises(c.DBError):
            c.advance(self.r, "PUBLISHED", "t")
        c.advance(self.r, "AUTHENTICITY_REVIEW", "t")
        c.advance(self.r, "ANALYSED", "t")
        with self.assertRaises(c.DBError):  # no score yet
            c.advance(self.r, "SCORED", "t")

    def walk(self, rights, auth="verified_by_review"):
        self.r.update(scores={"total": 7}, rights=rights, authenticity=auth, stage="PRODUCED")
        c.advance(self.r, "APPROVED_FOR_PUBLICATION", "t")

    def test_unverified_rights_never_reach_publication_queue(self):
        for rights in ("unverified", "unresolved", "refused"):
            with self.assertRaises(c.DBError):
                self.walk(rights)
        self.assertEqual(c.publication_queue(self.db), [])

    def test_unverified_authenticity_blocked(self):
        with self.assertRaises(c.DBError):
            self.walk("owned", "category_only")

    def test_publishable_record_enters_queue(self):
        self.walk("owned")
        self.assertEqual(len(c.publication_queue(self.db)), 1)

    def test_history_and_search(self):
        c.set_fields(self.r, "t", "n", editorial_notes="hello")
        log = (c.ROOT / "db" / "history.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(log[-1])["changes"]["editorial_notes"], ["", "hello"])
        self.assertEqual(len(c.search(self.db, creator="dem", platform="kick")), 1)
        self.assertEqual(c.search(self.db, min_score=1), [])

    def test_sync_is_repeatable_and_valid(self):
        self.r.update(metrics={"motion": 1}, scores={"total": 5}, rights="credited_third_party", status="analysed")
        c.sync(self.db)
        self.assertEqual(self.r["stage"], "RIGHTS_RECORDED")
        self.assertEqual(c.sync(self.db), 0)
        self.assertEqual(c.validate(self.db), [])

    def test_backup_restore_and_damaged_file(self):
        c.save(self.db)
        z = c.backup()
        out = c.ROOT / "restored"
        c.restore(z, out)
        self.assertEqual(json.loads((out / "db" / "clips.json").read_text(encoding="utf-8")), self.db)
        (c.ROOT / "db" / "clips.json").write_text("{broken", encoding="utf-8")
        with self.assertRaises(c.DBError):
            c.load()


if __name__ == "__main__":
    unittest.main()
