"""Real image/video fixtures plus failure/undo checks; no user data/network."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, env, filename):
    spec = importlib.util.spec_from_file_location(name, os.environ.get(env, str(HERE / filename)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load('audit', 'CONTABO_PHOTO_AUDIT_SCRIPT', 'photo-metadata-audit.py')
mtime = load('mtime', 'CONTABO_MTIME_REPAIR_SCRIPT', 'photo-mtime-repair.py')
photo = load('remediation', 'CONTABO_PHOTO_REMEDIATION_SCRIPT', 'photo-remediation.py')


class Pairing(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.media = self.root / 'photo.jpg'

    def sidecar(self, name, timestamp=946684800, **extra):
        path = self.root / name
        path.write_text(json.dumps({'photoTakenTime': {'timestamp': str(timestamp)}, **extra}))
        return path

    def test_agreeing_exact_duplicates_are_usable(self):
        a = self.sidecar('photo.jpg.json')
        b = self.sidecar('photo.jpg.supplemental-metadata.json')
        result, error = photo.matching_sidecar(self.media, [a, b], {}, audit)
        self.assertIsNone(error)
        self.assertEqual(result['epoch'], 946684800)

    def test_conflicting_duplicates_are_never_chosen(self):
        a = self.sidecar('photo.jpg.json')
        b = self.sidecar('photo.jpg.supplemental-metadata.json', timestamp=1500000000)
        result, error = photo.matching_sidecar(self.media, [a, b], {}, audit)
        self.assertIsNone(result)
        self.assertEqual(error, 'ambiguous_sidecars')

    def test_title_match_must_be_unique_and_exact(self):
        a = self.sidecar('truncated.json', title='photo.jpg')
        result, error = photo.matching_sidecar(self.media, [a], {'photo.jpg': [a]}, audit)
        self.assertIsNone(error)
        self.assertEqual(result['pairing'], 'unique_takeout_title')
        b = self.sidecar('other.json', title='photo.jpg')
        self.assertEqual(photo.matching_sidecar(self.media, [a, b], {'photo.jpg': [a, b]}, audit)[1],
                         'ambiguous_sidecars')
        self.assertEqual(photo.matching_sidecar(self.media, [a], {'photo.jpg-edited': [a]}, audit)[1],
                         'missing_sidecar')


@unittest.skipUnless(shutil.which('exiftool') and shutil.which('ffmpeg'), 'Needs real ExifTool and FFmpeg')
class RealMedia(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'photos'
        self.root.mkdir()
        self.undo = self.base / 'metadata-journals'
        self.patches = [patch.object(mtime, 'ROOT', self.root),
                        patch.object(photo, 'JOURNALS', self.undo),
                        patch.object(mtime, 'check_root'),
                        patch.object(mtime, 'backup', return_value='a' * 64),
                        patch.object(mtime, 'scoped_scan'),
                        patch.object(photo.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 100 * 1024**3})())]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.tool = photo.Remediation(audit, mtime)

    def fixture(self, extension, name='sample'):
        path = self.root / (name + extension)
        args = ['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=32x32:d=0.1']
        if extension in ('.mp4', '.mov'):
            args += ['-c:v', 'mpeg4']
        else:
            args += ['-frames:v', '1', '-threads', '1']
        subprocess.run([*args, str(path)], check=True, capture_output=True)
        sidecar = path.with_name(path.name + '.json')
        sidecar.write_text(json.dumps({'photoTakenTime': {'timestamp': '946684800'}}))
        os.utime(path, ns=(1700000000000000000, 1700000000000000000))
        return path

    def test_supported_formats_roundtrip_exact_bytes_and_inode(self):
        for extension in ('.jpg', '.png', '.tiff', '.webp', '.mp4', '.mov'):
            with self.subTest(extension=extension):
                path = self.fixture(extension, extension[1:])
                original = path.read_bytes()
                original_stat = path.stat()
                plan = self.tool.plan()
                rows = [r for r in plan['metadata'] if r['rel'] == path.name]
                self.assertEqual(len(rows), 1, plan)
                folder = self.tool.apply_metadata(rows)
                self.assertNotEqual(path.read_bytes(), original)
                self.assertEqual(path.stat().st_mtime_ns, original_stat.st_mtime_ns)
                self.assertFalse([r for r in self.tool.plan()['metadata'] if r['rel'] == path.name])
                self.tool.restore(folder)
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(path.stat().st_ino, original_stat.st_ino)
                self.assertEqual(path.stat().st_mtime_ns, original_stat.st_mtime_ns)

    def test_conflicting_photo_does_not_block_safe_photo(self):
        bad = self.fixture('.jpg', 'conflict')
        good = self.fixture('.jpg', 'safe')
        subprocess.run(['exiftool', '-overwrite_original', '-DateTimeOriginal=2020:01:01 00:00:00', str(bad)],
                       check=True, capture_output=True)
        before = bad.read_bytes()
        plan = self.tool.plan()
        self.assertEqual([r['rel'] for r in plan['mtimes']], [good.name])
        self.assertEqual([r['reason'] for r in plan['exceptions']], ['embedded_date_conflict'])
        self.tool.apply_metadata(plan['metadata'])
        self.assertEqual(bad.read_bytes(), before)

    def test_payload_mismatch_never_replaces_original(self):
        path = self.fixture('.jpg')
        before = path.read_bytes()
        rows = self.tool.plan()['metadata']
        with patch.object(self.tool, 'media_hash', side_effect=['original frames', 'changed frames']):
            with self.assertRaises(RuntimeError):
                self.tool.apply_metadata(rows)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_nlink, 1)

    def test_incomplete_batch_is_rolled_back_on_resume(self):
        path = self.fixture('.png')
        before = path.read_bytes()
        folder = self.tool.apply_metadata(self.tool.plan()['metadata'])
        (folder / 'complete.json').unlink()
        self.tool.recover()
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue((folder / 'rolled-back.json').is_file())

    def test_later_failure_rolls_back_already_replaced_files(self):
        a = self.fixture('.jpg', 'a')
        b = self.fixture('.jpg', 'b')
        originals = {p: (p.read_bytes(), p.stat().st_ino) for p in (a, b)}
        rows = self.tool.plan()['metadata']
        actual = self.tool.media_hash
        calls = 0
        def checksum(path):
            nonlocal calls
            calls += 1
            return 'bad frames' if calls == 4 else actual(path)
        with patch.object(self.tool, 'media_hash', side_effect=checksum):
            with self.assertRaises(RuntimeError):
                self.tool.apply_metadata(rows)
        for path, (data, inode) in originals.items():
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(path.stat().st_ino, inode)
            self.assertEqual(path.stat().st_nlink, 1)

    def test_interruption_after_undo_link_before_replace_recovers_single_link(self):
        path = self.fixture('.png')
        before = path.read_bytes()
        folder = self.tool.apply_metadata(self.tool.plan()['metadata'])
        (folder / 'complete.json').unlink()
        backup = folder / 'original-000000'
        path.unlink()
        os.link(backup, path)
        self.assertEqual(path.stat().st_nlink, 2)
        self.tool.recover()
        self.assertEqual(path.stat().st_nlink, 1)
        self.assertEqual(path.read_bytes(), before)

    def test_changed_source_is_not_overwritten_during_undo(self):
        path = self.fixture('.jpg')
        folder = self.tool.apply_metadata(self.tool.plan()['metadata'])
        path.write_bytes(b'changed outside repair')
        with self.assertRaises(RuntimeError):
            self.tool.restore(folder)
        self.assertEqual(path.read_bytes(), b'changed outside repair')

    def test_unsafe_path_is_not_repaired(self):
        path = self.fixture('.jpg')
        rows = self.tool.plan()['metadata']
        rows[0]['rel'] = '../outside.jpg'
        with self.assertRaises(RuntimeError):
            self.tool.apply_metadata(rows)
        self.assertTrue(path.is_file())


if __name__ == '__main__':
    unittest.main()
