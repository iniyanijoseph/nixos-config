"""Tests for DM + one-guild archive selection (old records preserved)."""
import importlib.util
from pathlib import Path
import sqlite3
import unittest

scope_path=Path(__file__).with_name("discord-archive")/"scope.py"
spec=importlib.util.spec_from_file_location("discord_scope",scope_path)
scope=importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)

class ScopeTests(unittest.TestCase):
    def test_selects_dms_one_guild_and_its_threads(self):
        con=sqlite3.connect(":memory:")
        con.row_factory=sqlite3.Row
        con.execute("CREATE TABLE channels(id TEXT, kind TEXT)")
        con.executemany("INSERT INTO channels VALUES (?,?)",[
            ("1","dms"),
            ("10","guild:804408079940583475"),
            ("11","guild:999"),
            ("20","archived-public:10"),
            ("21","archived-private:11"),
            ("22","threads-active:804408079940583475"),
            ("23","threads-active:999")])
        self.assertEqual({r["id"] for r in scope.selected_rows(con)},{"1","10","20","22"})
        parents=scope.selected_parent_ids(con)
        self.assertTrue(scope.selected_scan("archived-public:10",parents))
        self.assertFalse(scope.selected_scan("archived-private:11",parents))
        self.assertFalse(scope.selected_scan("guild:999",parents))
        self.assertTrue(scope.selected_scan("guild:804408079940583475",parents))
        con.close()
if __name__=="__main__":
    unittest.main()
