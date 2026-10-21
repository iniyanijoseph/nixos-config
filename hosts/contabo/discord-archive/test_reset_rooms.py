import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("discord_reset", ROOT / "reset_rooms.py")
reset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset)


class ResetTests(unittest.TestCase):
    def test_scoped_room_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            filename = Path(temp) / "old.sqlite"
            db = sqlite3.connect(filename)
            db.execute("CREATE TABLE portal(mxid TEXT)")
            db.execute("CREATE TABLE guild(mxid TEXT)")
            db.execute('CREATE TABLE "user"(management_room TEXT,space_room TEXT,dm_space_room TEXT)')
            db.executemany("INSERT INTO portal(mxid) VALUES(?)", [
                ("!discorddm:iniyanjoseph.com",),
                ("!something-else:another-server.org",),
                (None,)
            ])
            db.execute("INSERT INTO guild(mxid) VALUES('!guild:iniyanjoseph.com')")
            db.execute("""INSERT INTO "user" VALUES(
                '!management:iniyanjoseph.com',
                '!space:iniyanjoseph.com',
                '!dmspace:iniyanjoseph.com')""")
            db.commit()
            db.close()
            rooms = reset.rooms_from_database(filename)
            self.assertEqual(rooms, sorted([
                "!discorddm:iniyanjoseph.com",
                "!guild:iniyanjoseph.com",
                "!management:iniyanjoseph.com",
                "!space:iniyanjoseph.com",
                "!dmspace:iniyanjoseph.com"
            ]))

    def test_no_database_is_not_empty_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(RuntimeError):
                reset.rooms_from_database(Path(temp) / "missing.sqlite")


if __name__ == "__main__":
    unittest.main()
