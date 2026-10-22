"""Offline tests: no Discord, Nextcloud, or Stalwart network calls."""
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().with_name("migration-queue.py")
sys.path.insert(0, str(SCRIPT.parent))
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

    def test_nested_duplicate_cleanup_keeps_canonical_files(self):
        import photo_reconcile as cleaner

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "Nextcloud"
            root.mkdir()
            canonical = root / "Photos from 2026" / "photo.jpg"
            canonical.parent.mkdir()
            canonical.write_bytes(b"2026 photograph")
            # Legitimate 2016 content must stay in place.
            genuine = root / "Photos from 2016" / "old.jpg"
            genuine.parent.mkdir()
            genuine.write_bytes(b"2016 photograph")
            misplaced = root / "Photos from 2016" / "Photos from 2026" / "photo.jpg"
            misplaced.parent.mkdir()
            misplaced.write_bytes(b"2026 photograph")
            import hashlib
            def record(value):
                return {"size": len(value), "sha256": hashlib.sha256(value).hexdigest()}
            manifest = {"format": 1, "files": {
                "Photos from 2026/photo.jpg": record(b"2026 photograph"),
                "Photos from 2016/old.jpg": record(b"2016 photograph"),
            }}
            result = cleaner.audit(root, manifest)
            self.assertTrue(result["ok"], result["reason"])
            self.assertEqual(result["duplicates"], [
                ("Photos from 2016/Photos from 2026/photo.jpg", "Photos from 2026/photo.jpg")
            ])
            observation = base / "observed.json"
            self.assertFalse(cleaner.stable_observation(
                result, observation, epoch=1000, quiet_seconds=3600)[0])
            self.assertFalse(cleaner.stable_observation(
                result, observation, epoch=4599, quiet_seconds=3600)[0])
            self.assertTrue(cleaner.stable_observation(
                result, observation, epoch=4600, quiet_seconds=3600)[0])
            moved = cleaner.quarantine_duplicates(
                root, manifest, result["duplicates"], base / "quarantine")
            self.assertEqual(moved, 1)
            self.assertFalse(misplaced.exists())
            self.assertEqual(canonical.read_bytes(), b"2026 photograph")
            self.assertEqual(genuine.read_bytes(), b"2016 photograph")
            self.assertTrue((base / "quarantine" /
                "Photos from 2016/Photos from 2026/photo.jpg").exists())
            ok, reason = queue.validate_manifest(manifest, root)
            self.assertTrue(ok, reason)

    def test_upload_does_not_qualify_until_canonical_copy_exists(self):
        import photo_reconcile as cleaner
        import hashlib

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Nextcloud"
            wrong = root / "Photos from 2016" / "Photos from 2026"
            wrong.mkdir(parents=True)
            (wrong / "photo.jpg").write_bytes(b"one")
            original = {"format": 1, "files": {
                "Photos from 2026/photo.jpg": {
                    "size": 3, "sha256": hashlib.sha256(b"one").hexdigest()
                }
            }}
            result = cleaner.audit(root, original)
            self.assertFalse(result["ok"])
            self.assertIn("canonical files missing", result["reason"])
            (root / "Photos from 2026").mkdir()
            (root / "Photos from 2026/photo.jpg").write_bytes(b"different")
            result = cleaner.audit(root, original)
            self.assertFalse(result["ok"])
            self.assertIn("mismatch", result["reason"].lower())
            (root / "Photos from 2026/photo.jpg").write_bytes(b"one")
            self.assertTrue(cleaner.audit(root, original)["ok"])
            (root / "Photos from 2016/Photos from 2026/photo.jpg").write_bytes(b"bad")
            self.assertFalse(cleaner.audit(root, original)["ok"])

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
