import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("discord_collector", ROOT / "collector.py")
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def msg(n):
    return {"id": str(n), "content": "test message", "author": {"id": "1"}}


class FakeAPI:
    def __init__(self, replies, fail_once=None):
        self.replies = replies
        self.fail_once = fail_once
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if self.fail_once == url:
            self.fail_once = None
            raise RuntimeError("simulated API failure")
        return self.replies[url]


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = collector.connect(Path(self.temp.name) / "archive.sqlite")
        collector.register(self.db, [{"id": "123", "name": "A DM"}], "manual")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_resume_historical_collection(self):
        replies = {
            "/channels/123/messages?limit=50": [msg(12), msg(11)],
            "/channels/123/messages?limit=50&before=11": [msg(10)],
            "/channels/123/messages?limit=50&before=10": [],
        }
        collector.fetch_history(self.db, FakeAPI(replies, "/channels/123/messages?limit=50&before=11"))
        row = self.db.execute("SELECT before_id,complete FROM channels").fetchone()
        self.assertEqual((row["before_id"], row["complete"]), ("11", 0))
        api = FakeAPI(replies)
        collector.fetch_history(self.db, api)
        self.assertEqual(api.calls[0], "/channels/123/messages?limit=50&before=11")
        self.assertEqual(collector.summary(self.db)["messages"], 3)
        self.assertEqual(self.db.execute("SELECT complete FROM channels").fetchone()[0], 1)

    def test_catch_up_resume_without_skipping(self):
        collector.fetch_history(self.db, FakeAPI({
            "/channels/123/messages?limit=50": [msg(11), msg(10)],
            "/channels/123/messages?limit=50&before=10": [],
        }))
        replies = {
            "/channels/123/messages?limit=50": [msg(14), msg(13)],
            "/channels/123/messages?limit=50&before=13": [msg(12), msg(11)]
        }
        collector.catch_up(self.db, FakeAPI(replies, "/channels/123/messages?limit=50&before=13"))
        self.assertEqual(self.db.execute("SELECT refresh_active FROM channels").fetchone()[0], 1)
        api = FakeAPI(replies)
        collector.catch_up(self.db, api)
        self.assertEqual(api.calls[0], "/channels/123/messages?limit=50&before=13")
        self.assertEqual(collector.summary(self.db)["messages"], 5)

    def test_guild_ids_are_not_channel_ids(self):
        api = FakeAPI({
            "/users/@me/channels": [],
            "/users/@me/guilds": [{"id": "555", "name": "Server"}],
            "/guilds/555/channels": [],
            "/guilds/555/threads/active": {"threads": []}
        })
        collector.discover(self.db, api)
        ids = [r[0] for r in self.db.execute("SELECT id FROM channels")]
        self.assertEqual(ids, ["123"])

    def test_discovery_failure_is_reported(self):
        api = FakeAPI({"/users/@me/channels": []}, fail_once="/users/@me/guilds")
        collector.discover(self.db, api)
        issues = collector.summary(self.db)["issues"]
        self.assertTrue(any("guilds" in issue for issue in issues))

    def test_error_diagnostics_are_safe(self):
        self.assertEqual(
            collector.error_summary(400, b'{"code":40333,"message":"request blocked"}',
                                    "/users/@me/guilds?with_counts=true"),
            "HTTP 400, Discord code 40333: /users/@me/guilds")
        self.assertEqual(
            collector.error_summary(400, b"<html>opaque response</html>",
                                    "/users/@me/channels"),
            "HTTP 400, non-JSON or unrecognized error response: /users/@me/channels")
        self.assertNotIn("secret", collector.error_summary(
            400, b'{"message":"secret value"}', "/users/@me"))

    def test_invalid_cursor_rejected(self):
        with self.assertRaises(ValueError):
            collector.page_ids([msg(4), msg(5)])
        with self.assertRaises(ValueError):
            collector.page_ids([msg(3), msg(3)])
        with self.assertRaises(ValueError):
            collector.page_ids([msg(6)], before="5")


if __name__ == "__main__":
    unittest.main()
