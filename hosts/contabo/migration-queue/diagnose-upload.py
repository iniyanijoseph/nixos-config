#!/usr/bin/env python3
"""Read-only location audit for original Google Takeout paths on Nextcloud."""
import collections
import json
from pathlib import Path

root = Path("/var/lib/nextcloud/data/wug/files/Photos/Google Photos")
manifest = json.loads(Path("/var/lib/migration-queue/photos-manifest.json").read_text())["files"]
by_name_size = collections.defaultdict(list)
present = set()
for file in root.rglob("*"):
    if file.is_symlink() or not file.is_file():
        continue
    rel = file.relative_to(root).as_posix()
    present.add(rel)
    by_name_size[(file.name, file.stat().st_size)].append(rel)

missing = sorted(set(manifest) - present)
elsewhere = []
absent = []
for rel in missing:
    info = manifest[rel]
    candidates = by_name_size.get((Path(rel).name, info["size"]), [])
    if candidates:
        elsewhere.append((rel, candidates))
    else:
        absent.append(rel)

print(f"Manifest entries: {len(manifest)}")
print(f"Files on disk: {len(present)}")
print(f"Missing exact expected path: {len(missing)}")
print(f"Missing but same filename/size elsewhere: {len(elsewhere)}")
print(f"No file with matching filename/size found: {len(absent)}")
print("\nFIRST 20 POSSIBLY MISPLACED:")
for expected, candidates in elsewhere[:20]:
    print("expected:", repr(expected))
    for candidate in candidates[:5]:
        print("   actual:", repr(candidate))
print("\nFIRST 20 WITHOUT FILENAME/SIZE MATCH:")
for expected in absent[:20]:
    print(repr(expected))
print("\nNOTE: matching filename/size is not proof of identical content; no changes made.")
