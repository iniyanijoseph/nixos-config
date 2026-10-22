"""Offline tests: no Discord, Nextcloud, or Stalwart network calls."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().with_name("migration-queue.py")
spec = importlib.util.spec_from_file_location("migration_queue", SCRIPT)
queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)


class QueueTests(unittest.TestCase):
    def test_manifest_detects_missing_and_modified_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "takeout"
            uploaded = root / "uploaded"
            original.mkdir()
            uploaded.mkdir()
            (original / "photo.jpg").write_bytes(b"unchanged photo")
            (original / "photo.jpg.json").write_bytes(b'{"description":"test"}')
            manifest = queue.build_manifest(original)
            self.assertFalse(queue.validate_manifest(manifest, uploaded)[0])
            for p in original.iterdir():
                (uploaded / p.name).write_bytes(p.read_bytes())
            self.assertTrue(queue.validate_manifest(manifest, uploaded)[0])
            (uploaded / "photo.jpg").write_bytes(b"different image")
            self.assertFalse(queue.validate_manifest(manifest, uploaded)[0])
            (uploaded / "photo.jpg").write_bytes(b"unchanged photo")
            (uploaded / "extra").write_bytes(b"unexpected")
            self.assertFalse(queue.validate_manifest(manifest, uploaded)[0])

    def test_discord_requires_finished_backfill_and_complete_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "discord.sqlite"
            db = sqlite3.connect(db_path)
            db.execute("""CREATE TABLE channels (
                 id TEXT, complete INTEGER, refresh_active INTEGER,
                 refreshed_at TEXT, error TEXT)""")
            db.execute("CREATE TABLE scans(scope TEXT, ok INTEGER)")
            db.execute("INSERT INTO channels VALUES ('100',1,0,'yesterday',NULL)")
            db.executemany("INSERT INTO scans VALUES(?,?)",
                           [("dms", 1), ("guilds", 1), ("threads-active:42", 0)])
            db.commit()
            db.close()
            with patch.object(queue, "discord_running", return_value=False):
                ok, why = queue.discord_status(db_path)
                self.assertFalse(ok, why)
                self.assertIn("incomplete discovery", why)
                db = sqlite3.connect(db_path)
                db.execute("UPDATE scans SET ok=1")
                db.commit()
                db.close()
                self.assertTrue(queue.discord_status(db_path)[0])
                db = sqlite3.connect(db_path)
                db.execute("UPDATE channels SET refreshed_at=NULL")
                db.commit()
                db.close()
                self.assertFalse(queue.discord_status(db_path)[0])
            with patch.object(queue, "discord_running", return_value=True):
                self.assertFalse(queue.discord_status(db_path)[0])

    def test_photo_index_failure_does_not_mark_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            migrated, indexed = temp / "migrated", temp / "indexed"
            with patch.object(queue, "MARK", migrated), \
                 patch.object(queue, "INDEX_MARK", indexed), \
                 patch.object(queue, "photos_status", return_value=(True, "verified")), \
                 patch.object(queue.subprocess, "run") as run:
                def execute(argv, **kwargs):
                    if "memories:index" in argv:
                        raise queue.subprocess.CalledProcessError(1, argv)
                run.side_effect = execute
                with self.assertRaises(queue.subprocess.CalledProcessError):
                    queue.photos_migrate()
                self.assertTrue(migrated.exists())
                self.assertFalse(indexed.exists())
                run.reset_mock()
                run.side_effect = None
                queue.photos_migrate()
                calls = [x.args[0] for x in run.call_args_list]
                self.assertEqual(len(calls), 1)
                self.assertIn("memories:index", calls[0])
                self.assertTrue(indexed.exists())


if __name__ == "__main__":
    unittest.main()
