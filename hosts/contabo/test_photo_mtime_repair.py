#!/usr/bin/env python3
"""Offline fixture tests for the photo mtime repair; no real user photos."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SOURCE = Path(os.environ.get(
    "CONTABO_MTIME_REPAIR_SCRIPT",
    str(Path(__file__).resolve().parent / "photo-mtime-repair.py")
))
spec = importlib.util.spec_from_file_location("photo_mtime_repair", SOURCE)
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)

class RepairTests(unittest.TestCase):
    def setup_fixture(self, root):
        media = root / "sample.jpg"
        sidecar = root / "sample.jpg.json"
        media.write_bytes(b"FAKE JPEG BYTES - DO NOT MODIFY")
        sidecar.write_text(json.dumps({"photoTakenTime": {"timestamp": "946684800"}}))
        os.utime(media, (1750000000, 1750000000))
        return media

    def test_inventory_avoids_mutation_and_is_exact(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            media = self.setup_fixture(root)
            before = media.stat().st_mtime_ns
            with mock.patch.object(repair, "ROOT", root):
                rows, counts = repair.inventory()
                self.assertEqual(counts["eligible"], 1)
                self.assertEqual(rows[0]["after"], 946684800000000000)
                self.assertEqual(media.stat().st_mtime_ns, before)
                (root / "sample.jpg.supplemental-metadata.json").write_text("{}")
                _, counts = repair.inventory()
                self.assertEqual(counts["eligible"], 0)
                self.assertEqual(counts["missing_or_ambiguous_sidecar"], 1)

    def test_apply_journal_and_rollback_restore_exact_mtime(self):
        with tempfile.TemporaryDirectory() as dirname:
            base = Path(dirname)
            root = base / "photos"
            root.mkdir()
            media = self.setup_fixture(root)
            before = media.stat().st_mtime_ns
            journal_root = base / "private-journals"
            with (mock.patch.object(repair, "ROOT", root),
                  mock.patch.object(repair, "JOURNALS", journal_root),
                  mock.patch.object(repair, "check_root"),
                  mock.patch.object(repair, "backup", return_value="a" * 64),
                  mock.patch.object(repair, "scoped_scan")):
                rows, _ = repair.inventory()
                repair.apply(rows, 1)
                self.assertEqual(media.stat().st_mtime_ns, 946684800000000000)
                self.assertEqual(media.read_bytes(), b"FAKE JPEG BYTES - DO NOT MODIFY")
                journals = list(journal_root.iterdir())
                self.assertEqual(len(journals), 1)
                self.assertTrue((journals[0] / "changes.jsonl").is_file())
                repair.rollback(journals[0])
                self.assertEqual(media.stat().st_mtime_ns, before)
                self.assertTrue(journals[0].is_dir())

if __name__ == "__main__":
    unittest.main()
