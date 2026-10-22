#!/usr/bin/env python3
"""Read-only SHA-256 content audit of Nextcloud Google Photos against Takeout.

A matching digest proves content equality, not album/path identity.
This script never modifies data or overrides the migration queue's safety gates.
"""
import collections
import hashlib
import json
from pathlib import Path

ROOT = Path("/var/lib/nextcloud/data/wug/files/Photos/Google Photos")
MANIFEST = Path("/var/lib/migration-queue/photos-manifest.json")
OUT = Path("/var/lib/migration-queue/photos-content-audit.json")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    originals = json.loads(MANIFEST.read_text())["files"]
    actual = {}
    by_content = collections.defaultdict(list)
    issues = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_symlink():
            issues.append("symlink: " + str(path.relative_to(ROOT)))
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            before = path.stat()
            key = (before.st_size, digest(path))
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                issues.append("changed during hashing: " + rel)
                continue
            actual[rel] = key
            by_content[key].append(rel)
        except OSError as exc:
            issues.append(f"unreadable {rel}: {exc}")
    exact = []
    recoverable = {}
    absent = []
    for rel, info in sorted(originals.items()):
        expected = (info["size"], info["sha256"])
        if actual.get(rel) == expected:
            exact.append(rel)
        elif expected in by_content:
            recoverable[rel] = by_content[expected]
        else:
            absent.append(rel)
    required = {(v["size"], v["sha256"]) for v in originals.values()}
    unexpected = [p for p, key in actual.items() if key not in required]
    unique_absent = {(originals[p]["size"], originals[p]["sha256"]) for p in absent}
    report = {
        "manifest_entries": len(originals),
        "server_files": len(actual),
        "exact_correct": len(exact),
        "recoverable_from_identical_content": len(recoverable),
        "unavailable_manifest_paths": len(absent),
        "unique_unavailable_contents": len(unique_absent),
        "unrecognized_server_files": len(unexpected),
        "errors": issues,
        "recoverable_examples": [
            {"expected": k, "candidates": v[:5]} for k, v in list(recoverable.items())[:25]
        ],
        "absent_examples": absent[:50],
        "unexpected_examples": unexpected[:25],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    # Do not write the report to the source directory. Report is printed;
    # save output outside the server's photo library if desired.


if __name__ == "__main__":
    main()
