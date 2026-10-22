#!/usr/bin/env python3
"""Safe SHA256-based Takeout recovery from files anywhere in upload tree.

Call only after one hour of identical full content inventory and successful
restic backup. Original paths may be added via hard links; no overwrites.
Redundant upload paths are moved to quarantine, not deleted.
"""
import hashlib
import json
import os
from pathlib import Path

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def inventory(root, originals):
    root=Path(root)
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError("Photo directory absent/symlinked")
    expected={(m["size"],m["sha256"]) for m in originals.values()}
    by_hash={}
    signatures=[]
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise RuntimeError(f"Symlink in photo upload: {p}")
        if not p.is_file():continue
        rel=p.relative_to(root).as_posix()
        a=p.stat()
        digest=sha(p)
        b=p.stat()
        sig=(a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)
        if sig!=(b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns,b.st_ctime_ns):
            raise RuntimeError(f"Upload changed during hashing: {rel}")
        key=(a.st_size,digest)
        if key not in expected:
            raise RuntimeError(f"Unknown content; manual review required: {rel}")
        by_hash.setdefault(key,[]).append(rel)
        signatures.append((rel,sig))
    missing=[rel for rel,m in originals.items() if (m["size"],m["sha256"]) not in by_hash]
    fingerprint=hashlib.sha256(json.dumps(signatures,sort_keys=True).encode()).hexdigest()
    return {"ok":not missing,"missing":sorted(missing),"by_hash":by_hash,
            "fingerprint":fingerprint,"actual_count":len(signatures)}

def restore(root,originals,quarantine):
    """Verify then restore originals with no-clobber hardlinks, quarantine extra paths."""
    root=Path(root); quarantine=Path(quarantine)
    report=inventory(root,originals)
    if not report["ok"]:
        raise RuntimeError(f"{len(report['missing'])} Takeout files still absent")
    if quarantine.resolve().is_relative_to(root.resolve()):
        raise RuntimeError("Quarantine cannot be inside photos folder")
    quarantine.mkdir(parents=True,mode=0o700,exist_ok=True)
    if root.stat().st_dev!=quarantine.stat().st_dev:
        raise RuntimeError("Quarantine must be on the same filesystem")
    restored=0
    for rel,m in sorted(originals.items()):
        if not rel or rel.startswith("/") or any(part in (".","..") for part in rel.split("/")):
            raise RuntimeError("Unsafe manifest path")
        target=root/rel
        key=(m["size"],m["sha256"])
        if target.exists():
            if target.is_symlink() or target.stat().st_size!=key[0] or sha(target)!=key[1]:
                raise RuntimeError(f"Cannot overwrite conflicting file: {rel}")
            continue
        candidates=report["by_hash"][key]
        source=root/candidates[0]
        if not source.is_file() or source.is_symlink() or sha(source)!=key[1]:
            raise RuntimeError(f"Source changed: {source}")
        target.parent.mkdir(parents=True,exist_ok=True)
        os.link(source,target,follow_symlinks=False) # Atomic, fails if target appeared.
        if sha(target)!=key[1]:
            raise RuntimeError(f"Linked copy changed: {rel}")
        restored+=1
    # Verify ALL canonical files exist before moving any original uploads.
    for rel,m in originals.items():
        p=root/rel
        if not p.is_file() or p.stat().st_size!=m["size"] or sha(p)!=m["sha256"]:
            raise RuntimeError(f"Canonical verification failed: {rel}")
    expected_paths=set(originals)
    moved=0
    for rels in report["by_hash"].values():
        for rel in rels:
            if rel in expected_paths:
                continue
            source=root/rel; destination=quarantine/rel
            if not source.exists():
                continue
            if destination.exists():
                raise RuntimeError(f"Quarantine collision: {rel}")
            destination.parent.mkdir(parents=True,exist_ok=True)
            source.rename(destination)
            moved+=1
    return {"restored":restored,"quarantined":moved}
