import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLOUD = Path(__file__).resolve().parent.parent / "cloud"
sys.path.insert(0, str(CLOUD))
import mergedb as M  # noqa: E402


class Merge(unittest.TestCase):
    base = [{"id": "a", "youtube": "pending", "tiktok": "pending"}]

    def test_both_sides_survive_and_statuses_never_go_back(self):
        server = [{"id": "a", "youtube": "posted 2026", "tiktok": "pending"}, {"id": "b"}]
        local = [{"id": "a", "youtube": "pending", "tiktok": "scheduled 2026", "slot_tiktok": "x"}, {"id": "c"}]
        out = {i["id"]: i for i in M.merge(self.base, server, local)}
        self.assertEqual(set(out), {"a", "b", "c"})
        self.assertEqual((out["a"]["youtube"], out["a"]["tiktok"]), ("posted 2026", "scheduled 2026"))
        clash = M.merge(self.base, [{**self.base[0], "youtube": "posted 1"}], [{**self.base[0], "youtube": "scheduled 1"}])
        self.assertEqual(clash[0]["youtube"], "posted 1")

    def test_removed_field_stays_removed_and_lines_are_unioned(self):
        base = {"x": {"hold": "h", "n": 1}}
        self.assertEqual(M.merge(base, {"x": {"n": 1}}, {"x": {"hold": "h", "n": 2}}), {"x": {"n": 2}})
        self.assertEqual(M.merge_text("1\n", "1\n2\n", "1\n3\n", "a.jsonl"), "1\n2\n3\n")

    def test_real_git_race_is_resolved_without_losing_data(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            d = Path(d)

            def git(where, *a):
                subprocess.run(["git", *a], cwd=where, check=True, capture_output=True)
            git(d, "init", "--bare", "-b", "main", "server.git")
            git(d, "clone", "server.git", "one")
            one = d / "one"
            (one / "cloud").mkdir()
            (one / "queue").mkdir()
            for f in ("save.py", "mergedb.py"):
                shutil.copy(CLOUD / f, one / "cloud" / f)
            (one / ".gitattributes").write_text("queue/*.json merge=vci\n")
            (one / "queue" / "m.json").write_text(json.dumps(self.base, indent=1))
            for k, v in (("user.name", "t"), ("user.email", "t@example.invalid")):
                git(one, "config", k, v)
            git(one, "add", "-A")
            git(one, "commit", "-m", "base")
            git(one, "push", "-u", "origin", "main")
            git(d, "clone", "server.git", "two")
            two = d / "two"
            for k, v in (("user.name", "t"), ("user.email", "t@example.invalid")):
                git(two, "config", k, v)
            for repo, change in ((one, {"youtube": "posted 1"}), (two, {"tiktok": "scheduled 2"})):
                (repo / "queue" / "m.json").write_text(json.dumps([{**self.base[0], **change}], indent=1))
                r = subprocess.run([sys.executable, "cloud/save.py", "change", "queue"], cwd=repo, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            final = json.loads((two / "queue" / "m.json").read_text())[0]
            self.assertEqual((final["youtube"], final["tiktok"]), ("posted 1", "scheduled 2"))


if __name__ == "__main__":
    unittest.main()
