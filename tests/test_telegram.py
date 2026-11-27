import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
import publisher as P  # noqa: E402
import telegram_bot as T  # noqa: E402

OWNER = "111"


class Bot(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        saved = {(P, n): getattr(P, n) for n in ("MANIFEST", "CALENDAR", "HISTORY", "ERRORS")}
        saved.update({(T, n): getattr(T, n) for n in ("call", "label", "OVERRIDES", "fetch")})
        self.addCleanup(lambda: [setattr(m, n, v) for (m, n), v in saved.items()])
        P.MANIFEST, P.CALENDAR, P.HISTORY, P.ERRORS = (d / n for n in ("m.json", "c.json", "h.jsonl", "e.jsonl"))
        T.OVERRIDES = d / "o.json"
        old = {k: os.environ.get(k) for k in ("TELEGRAM_CHAT_ID", "TELEGRAM_BOT_TOKEN")}
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.update({k: v}) for k, v in old.items()])
        os.environ.update(TELEGRAM_CHAT_ID=OWNER, TELEGRAM_BOT_TOKEN="test")
        self.calls, self.labels, self.updates = [], [], []

        def call(method, files=None, http_timeout=0, **data):
            self.calls.append((method, data))
            if method == "getUpdates":
                return [u for u in self.updates if u["update_id"] >= data.get("offset", 0)]
            return {"message_id": 5}
        T.call = call
        T.label = lambda issue, approve: self.labels.append((issue, approve))
        P.save(P.MANIFEST, [{"id": "v", "issue": 15, "title": "T", "rights": "licensed", "sources": [{"content_id": "c"}],
                             "video_url": "https://x/v.mp4", "youtube": "awaiting approval", "tiktok": "awaiting approval"}])

    def press(self, data, who=OWNER, n=1):
        return {"update_id": n, "callback_query": {"id": "q", "from": {"id": int(who)}, "data": data,
                                                   "message": {"message_id": 5, "chat": {"id": int(who)}}}}

    def item(self):
        return P.load(P.MANIFEST, [])[0]

    def test_owner_approval_is_recorded_once(self):
        self.updates = [self.press("ok:15")]
        T.handle_updates()
        self.assertEqual(self.labels, [(15, True)])
        self.assertEqual((self.item()["youtube"], self.item()["tiktok"]), ("pending", "pending"))
        self.assertIn(("getUpdates", {"offset": 2, "limit": 1}), self.calls)
        T.handle(self.press("no:15"))  # a second press changes nothing
        self.assertEqual(self.labels, [(15, True)])
        self.assertEqual(self.item()["youtube"], "pending")

    def test_rejection(self):
        T.handle(self.press("no:15"))
        self.assertEqual(self.item()["tiktok"], "rejected by owner")

    def test_strangers_are_ignored(self):
        for u in (self.press("ok:15", who="999"), {"update_id": 2, "message": {"chat": {"id": 999}, "text": "ok 15"}},
                  {"update_id": 3, "message": {"chat": {"id": 999}, "text": "/pause"}}):
            self.assertIsNone(T.handle(u))
        self.assertEqual(self.labels, [])
        self.assertEqual(self.item()["youtube"], "awaiting approval")
        self.assertFalse(T.OVERRIDES.exists())

    def test_failed_decision_stays_unconfirmed(self):
        def broken(issue, approve):
            raise RuntimeError("github down")
        T.label = broken
        self.updates = [self.press("ok:15")]
        with self.assertRaises(RuntimeError):
            T.handle_updates()
        self.assertFalse([c for c in self.calls if c[0] == "getUpdates" and "offset" in c[1]])
        self.assertEqual(self.item()["youtube"], "awaiting approval")

    def test_each_video_is_sent_once(self):
        T.fetch = lambda url, folder: (lambda p: (p.write_bytes(b"x"), p)[1])(Path(folder) / "v.mp4")
        self.assertEqual(T.send_requests(), [15])
        self.assertEqual(T.send_requests(), [])
        sent = [d for m, d in self.calls if m == "sendVideo"]
        self.assertIn("ok:15", sent[0]["reply_markup"])

    def test_pause_command(self):
        T.handle({"update_id": 1, "message": {"chat": {"id": int(OWNER)}, "text": "/pause"}})
        self.assertTrue(json.loads(T.OVERRIDES.read_text(encoding="utf-8"))["paused"])


if __name__ == "__main__":
    unittest.main()
