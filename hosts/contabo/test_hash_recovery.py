"""Offline tests for hash-based recovery, no-overwrite and missing sidecars."""
import importlib.util
from pathlib import Path
import hashlib
import tempfile
import unittest

spec=importlib.util.spec_from_file_location("recovery",Path(__file__).with_name("migration-queue")/"hash-recovery.py")
recovery=importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)

def record(data):
    return {"size":len(data),"sha256":hashlib.sha256(data).hexdigest()}

class RecoveryTests(unittest.TestCase):
    def test_missing_metadata_only_if_manifest_lists_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"photos";root.mkdir()
            (root/"old-photo.jpg").write_bytes(b"old")
            self.assertTrue(recovery.inventory(root,{"old-photo.jpg":record(b"old")})["ok"])
            a=recovery.inventory(root,{"old-photo.jpg":record(b"old"),"old-photo.jpg.supplemental-metadata.json":record(b"{}")})
            self.assertFalse(a["ok"])
            self.assertEqual(a["missing"],["old-photo.jpg.supplemental-metadata.json"])

    def test_arbitrary_album_aliases_and_no_clobber(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"photos";root.mkdir()
            wrong=root/"Photos from 2016/Photos from 2026/example.jpg"
            wrong.parent.mkdir(parents=True);wrong.write_bytes(b"example")
            manifest={"Travel/example.jpg":record(b"example"),
                      "Photos from 2026/example.jpg":record(b"example")}
            state=recovery.inventory(root,manifest)
            self.assertTrue(state["ok"])
            outcome=recovery.restore(root,manifest,Path(temp)/"quarantine")
            self.assertEqual(outcome["restored"],2)
            self.assertEqual(outcome["quarantined"],1)
            for rel in manifest:
                self.assertEqual((root/rel).read_bytes(),b"example")
            self.assertFalse(wrong.exists())
            self.assertTrue((Path(temp)/"quarantine"/"Photos from 2016/Photos from 2026/example.jpg").exists())

    def test_unknown_content_blocks_all_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"photos";root.mkdir()
            (root/"bad.jpg").write_bytes(b"unrecognized")
            with self.assertRaisesRegex(RuntimeError,"Unknown content"):
                recovery.restore(root,{"expected.jpg":record(b"expected")},Path(temp)/"quarantine")
            self.assertTrue((root/"bad.jpg").exists())

    def test_missing_file_blocks_all_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"photos";root.mkdir()
            (root/"some.jpg").write_bytes(b"some")
            self.assertFalse(recovery.inventory(root,{"some.jpg":record(b"some"),"missing.jpg":record(b"missing")})["ok"])
            with self.assertRaisesRegex(RuntimeError,"still absent"):
                recovery.restore(root,{"some.jpg":record(b"some"),"missing.jpg":record(b"missing")},Path(temp)/"quarantine")

if __name__=="__main__":
    unittest.main()
