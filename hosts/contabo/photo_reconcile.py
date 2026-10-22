#!/usr/bin/env python3
"""Conservative Takeout upload verifier and duplicate quarantine.

Never call this until the Discord gate has passed. All audit operations are
read-only. Quarantine is only used after a full verified upload, a stable
observation interval, and a successful backup by the calling queue.
"""
import hashlib
import json
import os
from pathlib import Path
import time

MISPLACED_PREFIX = "Photos from 2016/"
QUIET_SECONDS = 3600


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_key(key):
    path = Path(key)
    return (bool(key) and not path.is_absolute() and
            all(part not in (".", "..") for part in key.split("/")) and
            path.as_posix() == key)


def quick_coverage(root, originals):
    """Cheap existence/size check: never hash gigabytes during upload."""
    accounted = set()
    for base, dirs, names in os.walk(root, followlinks=False):
        dirs.sort()
        names.sort()
        if any((Path(base) / dirname).is_symlink() for dirname in dirs):
            return False, "Unexpected symlinked directory"
        for name in names:
            file = Path(base) / name
            if file.is_symlink() or not file.is_file():
                return False, f"Unexpected special file: {file}"
            rel = file.relative_to(root).as_posix()
            candidate = rel
            if candidate not in originals and rel.startswith(MISPLACED_PREFIX):
                candidate = rel[len(MISPLACED_PREFIX):]
            info = originals.get(candidate)
            if not isinstance(info, dict) or "size" not in info or "sha256" not in info:
                return False, f"Unknown/misnested file: {rel}"
            if file.stat().st_size != info["size"]:
                return False, f"Incomplete or incorrect size: {rel}"
            accounted.add(candidate)
    missing = originals.keys() - accounted
    if missing:
        return False, f"{len(missing)} Takeout files not uploaded, e.g. {min(missing)}"
    return True, "Every Takeout file exists with expected size"


def audit(root, manifest):
    """Return an all-or-nothing candidate cleanup plan; never modify files.

    Only *extra* files nested under Photos from 2016 are candidates.
    An exact shadow copy can be quarantined when its canonical copy is
    verified, or safely relocated when the canonical copy is missing.
    Every input must match the manifest; no overwrite is ever allowed.
    """
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        return {"ok": False, "reason": f"Uploaded folder unavailable: {root}"}
    original = manifest.get("files") if manifest.get("format") == 1 else None
    if not isinstance(original, dict) or not original:
        return {"ok": False, "reason": "Invalid/empty Takeout manifest"}
    if any(not isinstance(k, str) or not safe_key(k) for k in original):
        return {"ok": False, "reason": "Unsafe manifest file name"}
    # As the browser is still uploading, avoid repeatedly hashing the
    # existing 13GB collection. Full hashes start only after EVERY
    # expected file is found at a canonical or permitted alternate path.
    quick_ok, quick_reason = quick_coverage(root, original)
    if not quick_ok:
        return {"ok": False, "reason": quick_reason}
    found = set()
    extras = []
    fingerprint = hashlib.sha256()
    for base, dirs, names in os.walk(root, followlinks=False):
        dirs.sort()
        names.sort()
        if any((Path(base) / dirname).is_symlink() for dirname in dirs):
            return {"ok": False, "reason": "Unexpected symlinked directory"}
        for name in names:
            path = Path(base) / name
            if not path.is_file() or path.is_symlink():
                return {"ok": False, "reason": f"Unexpected special file: {path}"}
            rel = path.relative_to(root).as_posix()
            expected = original.get(rel)
            is_extra = expected is None
            if is_extra:
                if not rel.startswith(MISPLACED_PREFIX):
                    return {"ok": False, "reason": f"Unknown upload file: {rel}"}
                canonical = rel[len(MISPLACED_PREFIX):]
                expected = original.get(canonical)
                if not isinstance(expected, dict):
                    return {"ok": False, "reason": f"Misplaced file has no Takeout counterpart: {rel}"}
                extras.append((rel, canonical))
            if not isinstance(expected, dict) or "size" not in expected or "sha256" not in expected:
                return {"ok": False, "reason": f"Invalid manifest metadata: {rel}"}
            try:
                before = path.stat()
                if before.st_size != expected["size"]:
                    return {"ok": False, "reason": f"Size mismatch / still uploading: {rel}"}
                match = sha256_file(path) == expected["sha256"]
                after = path.stat()
            except OSError as err:
                return {"ok": False, "reason": f"Reading uploaded file failed: {rel}: {err}"}
            signature = (before.st_dev, before.st_ino, before.st_size,
                         before.st_mtime_ns, before.st_ctime_ns)
            if signature != (after.st_dev, after.st_ino, after.st_size,
                             after.st_mtime_ns, after.st_ctime_ns):
                return {"ok": False, "reason": f"File changed while auditing: {rel}"}
            if not match:
                return {"ok": False, "reason": f"Hash mismatch / still uploading: {rel}"}
            fingerprint.update(json.dumps([rel, *signature], separators=(",", ":")).encode())
            fingerprint.update(b"\n")
            if not is_extra:
                found.add(rel)
    missing = original.keys() - found
    alternate_locations = {canonical for _, canonical in extras}
    truly_missing = missing - alternate_locations
    if truly_missing:
        sample = min(truly_missing)
        return {"ok": False, "reason": f"{len(truly_missing)} Takeout files missing everywhere; first: {sample}"}
    duplicates = [(rel, canonical) for rel, canonical in extras if canonical in found]
    relocations = [(rel, canonical) for rel, canonical in extras if canonical in missing]
    # Every original must be fully hash-matched at its canonical location
    # or at the ONE specifically permitted misplaced prefix.
    return {"ok": True,
            "reason": f"{len(found)} canonical, {len(relocations)} safely recoverable, "
                      f"{len(duplicates)} redundant; all manifest files accounted for",
            "duplicates": duplicates, "relocations": relocations,
            "fingerprint": fingerprint.hexdigest()}


def stable_observation(result, record_file, *, epoch=None, quiet_seconds=QUIET_SECONDS):
    """Return (stable, reason); write observation marker for future polls."""
    if not result["ok"]:
        if record_file.exists():
            record_file.unlink()
        return False, result["reason"]
    epoch = time.time() if epoch is None else epoch
    previous = None
    try:
        previous = json.loads(record_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if not previous or previous.get("fingerprint") != result["fingerprint"]:
        write_json(record_file, {"fingerprint": result["fingerprint"],
                                 "first_seen": epoch})
        return False, f"Upload verified; observing one hour of unchanged files (0/{quiet_seconds}s)"
    elapsed = max(0, epoch - float(previous.get("first_seen", epoch)))
    if elapsed < quiet_seconds:
        return False, f"Upload verified; unchanged for {int(elapsed)}/{quiet_seconds}s"
    return True, f"Upload stable for at least {int(elapsed)}s"


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + ".new")
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, sort_keys=True)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def relocate_missing(root, manifest, relocations):
    """Restore checked originals without ever overwriting a destination.

    Use atomic hardlink creation to prevent races with the upload client.
    The duplicate source is unlinked only after verifying the target.
    """
    root = Path(root)
    originals = manifest["files"]
    moved = 0
    for rel, canonical in relocations:
        if not rel.startswith(MISPLACED_PREFIX) or canonical != rel[len(MISPLACED_PREFIX):]:
            raise RuntimeError(f"Unsafe relocation: {rel}")
        if rel in originals or canonical not in originals:
            raise RuntimeError(f"Manifest conflict while relocating: {rel}")
        source = root / rel
        target = root / canonical
        if source.is_symlink() or not source.is_file() or target.exists() or target.is_symlink():
            raise RuntimeError(f"Cannot safely relocate, target/source changed: {rel}")
        expect = originals[canonical]
        if source.stat().st_size != expect["size"] or sha256_file(source) != expect["sha256"]:
            raise RuntimeError(f"Misplaced file changed since audit: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Fails with FileExistsError if an upload has created the target.
        # Never use rename/replace here: those can overwrite a late upload.
        os.link(source, target, follow_symlinks=False)
        if sha256_file(target) != expect["sha256"]:
            raise RuntimeError(f"Newly linked canonical file changed: {canonical}")
        source.unlink()
        moved += 1
    return moved


def quarantine_duplicates(root, manifest, duplicates, quarantine):
    """Move only exact extra copies to reversible quarantine outside Nextcloud.

    Precondition: the caller has obtained a recent Restic snapshot, and
    the audit has been unchanged for at least QUIET_SECONDS.
    On interruption, completed moves remain under a private quarantine.
    """
    root = Path(root)
    quarantine = Path(quarantine)
    quarantine.mkdir(mode=0o700, parents=True, exist_ok=True)
    if quarantine.resolve().is_relative_to(root.resolve()):
        raise RuntimeError("Quarantine must be outside the Nextcloud Files tree")
    if root.stat().st_dev != quarantine.stat().st_dev:
        raise RuntimeError("Quarantine must share a filesystem with Nextcloud (atomic rename)")
    originals = manifest["files"]
    moved = 0
    for rel, canonical in duplicates:
        if not rel.startswith(MISPLACED_PREFIX) or canonical != rel[len(MISPLACED_PREFIX):]:
            raise RuntimeError(f"Unsafe duplicate candidate: {rel}")
        if rel in originals or canonical not in originals:
            raise RuntimeError(f"Manifest conflict: {rel}")
        src = root / rel
        correct = root / canonical
        dest = quarantine / rel
        if src.is_symlink() or correct.is_symlink() or dest.exists() or dest.is_symlink():
            raise RuntimeError(f"Unsafe rename or quarantine collision: {rel}")
        if not src.is_file() or not correct.is_file():
            raise RuntimeError(f"Missing file during cleanup: {rel}")
        expected = originals[canonical]
        for candidate in (src, correct):
            if candidate.stat().st_size != expected["size"] or sha256_file(candidate) != expected["sha256"]:
                raise RuntimeError(f"File no longer matches original; refusing cleanup: {rel}")
        dest.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        # Rename preserves the copy; nothing is deleted, and no valid
        # canonical path is ever modified.
        src.rename(dest)
        if sha256_file(dest) != expected["sha256"]:
            if not src.exists():
                dest.rename(src)
            raise RuntimeError(f"Quarantined file changed during rename: {rel}")
        moved += 1
    return moved
