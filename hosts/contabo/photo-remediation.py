#!/usr/bin/env python3
"""Per-file Takeout repair with byte-preserving undo and decoded-media checks.

Only missing capture dates are filled. Conflicting dates, uncertain pairing,
unsupported media and failed decodes remain private exceptions. This module
is invoked by finish-setup.py after its service/backup preflight.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import uuid
import argparse
import importlib.util

JOURNALS = Path('/var/lib/migration-queue/photo-metadata-journals')
IMAGE_TYPES = {'JPEG', 'PNG', 'TIFF', 'WEBP'}
VIDEO_TYPES = {'MP4', 'MOV', 'M4V'}


def syncdir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json(path, obj):
    temp = path.with_suffix('.tmp')
    with temp.open('w') as stream:
        json.dump(obj, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    syncdir(path.parent)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity(path):
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1:
        raise RuntimeError('Nonregular, linked or symbolic photo refused')
    return {'dev': s.st_dev, 'ino': s.st_ino, 'size': s.st_size,
            'before': s.st_mtime_ns, 'atime': s.st_atime_ns,
            'mode': stat.S_IMODE(s.st_mode), 'uid': s.st_uid, 'gid': s.st_gid}


def matching_sidecar(media, candidates, titles, audit):
    exact = audit.resolve_sidecars(media, candidates)
    chosen = exact or titles.get(media.name, [])
    if not chosen:
        return None, 'missing_sidecar'
    values = []
    for path in chosen:
        if path.is_symlink() or not path.is_file():
            return None, 'unsafe_sidecar'
        epoch, gps, error = audit.epoch_of(path)
        if error:
            return None, 'invalid_sidecar'
        values.append((epoch, gps))
    # Multiple exact sidecars are usable only if ALL capture metadata agrees.
    # Filename-title fallback must be unique; do not choose among truncated files.
    if (not exact and len(chosen) != 1) or any(v != values[0] for v in values):
        return None, 'ambiguous_sidecars'
    return {'epoch': values[0][0], 'gps': values[0][1],
            'sidecars': [str(p) for p in chosen],
            'pairing': 'exact' if exact else 'unique_takeout_title'}, None


class Remediation:
    def __init__(self, audit, mtime):
        self.audit, self.mtime = audit, mtime
        self.root = mtime.ROOT

    def inspect(self, files):
        args = ['exiftool', '-json', '-n', '-FileType', '-Error', '-Warning',
                '-OffsetTimeOriginal', '-GPSLatitude', '-GPSLongitude',
                '-GPSLatitudeRef', '-GPSLongitudeRef',
                *['-' + key for key in self.audit.DATE_KEYS],
                *[str(p) for p in files]]
        result = subprocess.run(args, check=True, capture_output=True, text=True, timeout=180)
        rows = json.loads(result.stdout)
        if len(rows) != len(files) or any(
                row.get('SourceFile') != str(path) for row, path in zip(rows, files)):
            raise RuntimeError('ExifTool returned a mismatched file inventory')
        return rows

    def plan(self):
        self.mtime.check_root(False)
        counts, mtimes, metadata, exceptions = Counter(), [], [], []
        for folder, directories, names in os.walk(self.root, followlinks=False):
            directories[:] = sorted(d for d in directories if not (Path(folder) / d).is_symlink())
            sidecars = [Path(folder) / n for n in names if n.lower().endswith('.json')]
            titles = {}
            for sidecar in sidecars:
                if sidecar.is_symlink():
                    continue
                try:
                    obj = json.loads(sidecar.read_text())
                    title = obj.get('title') if isinstance(obj, dict) else None
                    if isinstance(title, str):
                        titles.setdefault(title, []).append(sidecar)
                except (OSError, ValueError):
                    continue
            files = sorted(Path(folder) / n for n in names if Path(n).suffix.lower() in self.mtime.EXTS)
            for start in range(0, len(files), 50):
                batch = files[start:start + 50]
                safe = []
                for path in batch:
                    try:
                        identity(path)
                        safe.append(path)
                    except RuntimeError:
                        exceptions.append({'rel': str(path.relative_to(self.root)), 'reason': 'unsafe_file'})
                        counts['unsafe_file'] += 1
                reports = self.inspect(safe) if safe else []
                for path, exif in zip(safe, reports):
                    counts['media'] += 1
                    row = {'rel': str(path.relative_to(self.root)), **identity(path)}
                    paired, error = matching_sidecar(path, sidecars, titles, self.audit)
                    if not error and (exif.get('Error') or exif.get('Warning')):
                        error = 'exif_error_or_warning'
                    state = self.audit.compare_date(paired['epoch'], exif) if paired else None
                    if not error and state == 'embedded_date_conflicts_with_takeout':
                        error = 'embedded_date_conflict'
                    if error:
                        counts[error] += 1
                        exceptions.append({**row, 'reason': error, 'exif': exif,
                                           'sidecars': [str(p) for p in self.audit.resolve_sidecars(path, sidecars)]})
                        continue
                    counts[paired['pairing']] += 1
                    row.update(paired)
                    row['after'] = row['epoch'] * 1_000_000_000
                    if abs(row['before'] - row['after']) > 60_000_000_000:
                        mtimes.append(row.copy())
                    if state == 'missing_embedded_date':
                        kind = exif.get('FileType')
                        # Do not overwrite malformed but nonempty date text.
                        present = [exif.get(k) for k in self.audit.DATE_KEYS]
                        unknown = any(v and v != '0000:00:00 00:00:00' for v in present)
                        if kind in IMAGE_TYPES | VIDEO_TYPES and not unknown:
                            metadata.append({**row, 'file_type': kind,
                                             'before_gps': self.audit.coordinates(exif)})
                        else:
                            counts['missing_date_needs_review'] += 1
                            exceptions.append({**row, 'reason': 'missing_date_needs_review', 'exif': exif})
        counts['mtime_eligible'] = len(mtimes)
        counts['metadata_eligible'] = len(metadata)
        return {'root': str(self.root), 'counts': dict(counts), 'mtimes': mtimes,
                'metadata': metadata, 'exceptions': exceptions}

    def media_hash(self, path):
        result = subprocess.run(
            ['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path),
             '-map', '0:v:0', '-map', '0:a?', '-f', 'streamhash', '-hash', 'sha256', '-'],
            check=True, capture_output=True, text=True, timeout=1800)
        if not result.stdout.strip() or 'SHA256=' not in result.stdout:
            raise RuntimeError('Decoded-media checksum unavailable')
        return result.stdout

    def validate_identity(self, row):
        path = self.root / row['rel']
        if path.is_absolute() and not path.parent.resolve().is_relative_to(self.root):
            raise RuntimeError('Photo escaped its canonical directory')
        current = identity(path)
        if any(current[k] != row[k] for k in ('dev', 'ino', 'size', 'before')):
            raise RuntimeError('Photo changed after planning')
        return path

    def validate_sidecars(self, row):
        source = self.root / row['rel']
        for name in row['sidecars']:
            path = Path(name)
            if path.parent != source.parent or path.is_symlink():
                raise RuntimeError('Photo sidecar moved or became unsafe')
            epoch, gps, error = self.audit.epoch_of(path)
            if error or epoch != row['epoch'] or gps != row['gps']:
                raise RuntimeError('Takeout capture metadata changed after planning')
            if row['pairing'] == 'unique_takeout_title':
                obj = json.loads(path.read_text())
                if obj.get('title') != source.name:
                    raise RuntimeError('Takeout filename pairing changed after planning')

    def restore(self, folder):
        """Rollback OR finish an interrupted rollback without duplicating backups."""
        if folder.is_symlink() or folder.resolve().parent != JOURNALS.resolve():
            raise RuntimeError('Journal outside protected metadata directory')
        manifest = json.loads((folder / 'manifest.json').read_text())
        if manifest.get('root') != str(self.root) or manifest.get('format') != 1:
            raise RuntimeError('Metadata journal root/version mismatch')
        for entry in sorted(folder.glob('entry-*.json'), reverse=True):
            row = json.loads(entry.read_text())
            target = self.root / row['rel']
            if not target.parent.resolve().is_relative_to(self.root) or target.is_symlink():
                raise RuntimeError('Unsafe rollback path')
            backup = folder / row['backup']
            if backup.parent != folder or backup.is_symlink():
                raise RuntimeError('Unsafe original backup path')
            current = digest(target)
            if current == row['before_sha']:
                # Interrupted before replacement, or already rolled back.
                if backup.exists():
                    if digest(backup) != current:
                        raise RuntimeError('Original backup hash mismatch')
                    if os.path.samefile(target, backup):
                        backup.unlink()
                    else:
                        os.replace(backup, target)
            elif current == row['after_sha'] and backup.is_file() and digest(backup) == row['before_sha']:
                os.replace(backup, target)  # Restore original inode/bytes/mtime/owner.
            else:
                raise RuntimeError('Photo changed after metadata repair; automatic rollback refused')
            syncdir(target.parent)
        write_json(folder / 'rolled-back.json', {'complete': True})
        self.mtime.scoped_scan()

    def recover(self):
        # An incomplete batch is rolled back before making a new plan. Completed
        # batches keep their backups for deliberate later rollback.
        if JOURNALS.exists():
            for folder in sorted(JOURNALS.iterdir()):
                if folder.is_dir() and (folder / 'manifest.json').is_file() and not (
                        (folder / 'complete.json').exists() or (folder / 'rolled-back.json').exists()):
                    self.restore(folder)

    def apply_metadata(self, rows):
        self.mtime.check_root(True)
        if not rows:
            return None
        # Temporary edited copy + retained original. Refuse instead of deleting
        # archives or exceeding the existing disk safety reserve.
        required = sum(r['size'] for r in rows) + max(r['size'] for r in rows)
        if shutil.disk_usage(self.root).free < required + 5 * 1024**3:
            raise RuntimeError('Insufficient space for byte-preserving metadata rollback')
        snapshot = self.mtime.backup()
        JOURNALS.mkdir(parents=True, mode=0o700, exist_ok=True)
        folder = JOURNALS / uuid.uuid4().hex
        folder.mkdir(mode=0o700)
        syncdir(JOURNALS)
        write_json(folder / 'manifest.json', {'format': 1, 'root': str(self.root), 'snapshot': snapshot})
        print('Metadata rollback journal: ' + str(folder), flush=True)
        try:
            for index, row in enumerate(rows):
                source = self.validate_identity(row)
                self.validate_sidecars(row)
                if source.stat().st_dev != folder.stat().st_dev:
                    raise RuntimeError('Metadata undo must share the photo filesystem to retain its inode')
                original_hash = digest(source)
                payload = self.media_hash(source)
                descriptor, temp_name = tempfile.mkstemp(prefix='.contabo-metadata-', suffix=source.suffix,
                                                        dir=folder)
                os.close(descriptor)
                temp = Path(temp_name)
                try:
                    shutil.copyfile(source, temp, follow_symlinks=False)
                    date = datetime.fromtimestamp(row['epoch'], timezone.utc).strftime('%Y:%m:%d %H:%M:%S')
                    tags = (['-EXIF:DateTimeOriginal=' + date, '-EXIF:OffsetTimeOriginal=+00:00']
                            if row['file_type'] in IMAGE_TYPES else
                            ['-api', 'QuickTimeUTC=1', '-QuickTime:CreateDate=' + date + '+00:00',
                             '-Keys:CreationDate=' + date + '+00:00'])
                    subprocess.run(['exiftool', '-overwrite_original', '-P', *tags, str(temp)],
                                   check=True, capture_output=True, text=True, timeout=180)
                    after = self.inspect([temp])[0]
                    offset = self.audit.best_date_offset(row['epoch'], after)
                    if (after.get('Error') or after.get('Warning') or offset is None or abs(offset) > 1
                            or self.audit.coordinates(after) != row['before_gps']
                            or self.media_hash(temp) != payload):
                        raise RuntimeError('Metadata verification or decoded-media checksum failed')
                    self.validate_identity(row)
                    self.validate_sidecars(row)
                    if digest(source) != original_hash:
                        raise RuntimeError('Original bytes changed during metadata verification')
                    shutil.copystat(source, temp, follow_symlinks=False)
                    os.chown(temp, row['uid'], row['gid'])
                    os.chmod(temp, row['mode'])
                    os.utime(temp, ns=(row['atime'], row['before']))
                    with temp.open('rb') as stream:
                        os.fsync(stream.fileno())
                    entry = {**row, 'before_sha': original_hash, 'after_sha': digest(temp),
                             'backup': f'original-{index:06d}'}
                    write_json(folder / f'entry-{index:06d}.json', entry)
                    backup = folder / entry['backup']
                    os.link(source, backup, follow_symlinks=False)
                    syncdir(folder)
                    linked, live = backup.lstat(), source.lstat()
                    if ((linked.st_dev, linked.st_ino, linked.st_size, linked.st_mtime_ns) !=
                            (row['dev'], row['ino'], row['size'], row['before']) or
                            (live.st_dev, live.st_ino) != (linked.st_dev, linked.st_ino)):
                        raise RuntimeError('Original file changed before metadata replacement')
                    # Only swap the verified copy after undo data is durable.
                    os.replace(temp, source)
                    syncdir(source.parent)
                    syncdir(folder)
                finally:
                    temp.unlink(missing_ok=True)
            self.mtime.scoped_scan()
            write_json(folder / 'complete.json', {'changed': len(rows)})
        except Exception:
            self.restore(folder)
            raise
        return folder


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rollback', type=Path)
    parser.add_argument('--confirm', default='')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    audit = load('photo_audit', os.environ.get('CONTABO_PHOTO_AUDIT_SCRIPT', str(here / 'photo-metadata-audit.py')))
    mtime = load('mtime_repair', os.environ.get('CONTABO_MTIME_REPAIR_SCRIPT', str(here / 'photo-mtime-repair.py')))
    tool = Remediation(audit, mtime)
    if args.rollback:
        mtime.check_root(True)
        if args.confirm != 'ROLLBACK-PHOTO-METADATA':
            parser.error('Rollback needs --confirm ROLLBACK-PHOTO-METADATA')
        tool.restore(args.rollback)
        subprocess.run([str(mtime.OCC), 'memories:index', '--user=wug',
                        '--path=Photos/Google Photos', '--force'], check=True, timeout=14400)
        print('Original media bytes and metadata restored; scoped cache rescanned.')
    else:
        plan = tool.plan()
        print('Read-only per-file repair plan; private paths omitted.')
        print(json.dumps(plan['counts'], sort_keys=True))
        print('Exception classes: ' + json.dumps(dict(Counter(r['reason'] for r in plan['exceptions'])), sort_keys=True))


if __name__ == '__main__':
    main()
