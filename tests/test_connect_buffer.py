import contextlib
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import connect_buffer as C  # noqa: E402

KEY = "made-up-key-" + "x" * 30


class Connect(unittest.TestCase):
    def setUp(self):
        old = {n: getattr(C, n) for n in ("clipboard", "clear_clipboard", "github_signed_in", "subprocess")}
        old_channels = C.buffer_post.channels
        before = os.environ.get("BUFFER_API_KEY")
        self.addCleanup(lambda: [setattr(C, n, v) for n, v in old.items()])
        self.addCleanup(setattr, C.buffer_post, "channels", old_channels)
        self.addCleanup(lambda: os.environ.pop("BUFFER_API_KEY", None) if before is None else os.environ.update(BUFFER_API_KEY=before))
        self.saved = {}

        class Fake:
            @staticmethod
            def run(cmd, input=None, **kw):
                if cmd[:3] == ["gh", "secret", "set"]:
                    self.saved[cmd[3]] = input
                return subprocess.CompletedProcess(cmd, 0, "", "")
        C.subprocess, C.github_signed_in = Fake, lambda: True
        C.clipboard, C.clear_clipboard = lambda: KEY + "\n", lambda: None
        C.buffer_post.channels = lambda: {"youtube": "y"}

    def test_saves_a_checked_key_without_printing_it(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            C.main()
        self.assertEqual(self.saved, {"BUFFER_API_KEY": KEY})
        self.assertNotIn(KEY, out.getvalue())
        self.assertIn("tiktok", out.getvalue())

    def test_nothing_is_saved_for_a_copied_command_or_a_refused_key(self):
        C.clipboard = lambda: 'python "x.py"'
        with self.assertRaises(SystemExit):
            C.main()

        def refuse():
            raise RuntimeError("Buffer 401")
        C.clipboard, C.buffer_post.channels = lambda: KEY, refuse
        with self.assertRaises(SystemExit):
            C.main()
        self.assertEqual(self.saved, {})


if __name__ == "__main__":
    unittest.main()
