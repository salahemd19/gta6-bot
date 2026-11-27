import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import connect_telegram as C  # noqa: E402

TOKEN = "123456789:" + "A" * 35  # made-up shape, not a real token


class Connect(unittest.TestCase):
    def setUp(self):
        old = {n: getattr(C, n) for n in ("clipboard", "clear_clipboard", "api", "github_signed_in", "subprocess")}
        self.addCleanup(lambda: [setattr(C, n, v) for n, v in old.items()])
        self.saved, self.cleared, self.code = {}, [], None

        class Fake:
            @staticmethod
            def run(cmd, input=None, **kw):
                if cmd[:3] == ["gh", "secret", "set"]:
                    self.saved[cmd[3]] = input
                return subprocess.CompletedProcess(cmd, 0, "", "")

        def api(token, method, **data):
            if method == "getMe":
                return {"username": "demo_bot"}
            if method == "getUpdates" and "timeout" in data:
                code = self.out.getvalue().split()[-1]
                return [{"update_id": 1, "message": {"chat": {"type": "private", "id": 999}, "text": "000000x"}},
                        {"update_id": 2, "message": {"chat": {"type": "private", "id": 42, "first_name": "Owner"}, "text": code}}]
            return []
        C.subprocess, C.api, C.github_signed_in = Fake, api, lambda: True
        C.clipboard, C.clear_clipboard = lambda: f"Use this token: {TOKEN}\n", lambda: self.cleared.append(True)

    def test_binds_only_the_chat_that_sends_the_code_and_never_prints_the_token(self):
        self.out = io.StringIO()
        with contextlib.redirect_stdout(self.out):
            C.main()
        self.assertEqual(self.saved, {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "42"})
        self.assertNotIn(TOKEN, self.out.getvalue())
        self.assertTrue(self.cleared)

    def test_stops_cleanly_without_a_token(self):
        C.clipboard = lambda: "something else"
        with self.assertRaises(SystemExit) as e:
            C.main()
        self.assertIn("No bot token", str(e.exception))
        self.assertEqual(self.saved, {})


if __name__ == "__main__":
    unittest.main()
