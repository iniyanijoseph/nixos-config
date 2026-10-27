#!/usr/bin/env python3
"""Restore only Files mtimes from unambiguous Google Takeout JSON; no EXIF edits.

Read-only unless --apply. Apply obtains a fresh Restic snapshot, journals each
old mtime durably, then runs a path-scoped Nextcloud files:scan. --rollback
restores recorded original mtimes after inode and size checks.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path("/var/lib/nextcloud/data/wug/files/Photos/Google Photos")
JOURNALS = Path("/var/lib/migration-queue/photo-mtime-journals")
OCC = Path("/run/current-system/sw/bin/nextcloud-occ")
OCC_PATH = "/wug/files/Photos/Google Photos"
EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif",
        ".tiff", ".gif", ".bmp", ".mp4", ".mov", ".m4v", ".avi",
        ".3gp", ".mts", ".mkv"}
SIDE = (".json", ".supplemental-metadata.json",
        ".supplemental-metadata(1).json")

def check_root(mutating):
    if ROOT.is_symlink() or not ROOT.is_dir():
        raise RuntimeError("Photo directory missing or unsafe")
    if mutating:
        if os.geteuid() != 0 or os.uname().nodename.split(".")[0] != "contabo":
            raise RuntimeError("Mutations restricted to root on Contabo")
        if not OCC.is_file():
            raise RuntimeError("Nextcloud OCC wrapper missing")

def capture_time(path):
    try:
        with path.open(encoding="utf-8") as fd:
            data = json.load(fd)
        val = data.get("photoTakenTime", {}).get("timestamp")
        if isinstance(val, bool) or not isinstance(val, (str, int)):
            return None
        ts = int(val)
        return ts if 631152000 <= ts <= 4102444800 else None
    except (ValueError, TypeError, OSError, AttributeError):
        return None

def inventory():
    counts, rows = Counter(), []
    for folder, dirs, files in os.walk(ROOT, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(folder) / d).is_symlink())
        names = set(files)
        for name in sorted(files):
            target = Path(folder) / name
            if target.suffix.lower() not in EXTS:
                continue
            counts["media"] += 1
            if target.is_symlink() or not target.is_file():
                counts["unsafe_files"] += 1
                continue
            matches = [target.parent / (name + ext) for ext in SIDE
                       if name + ext in names]
            if len(matches) != 1 or matches[0].is_symlink() or not matches[0].is_file():
                counts["missing_or_ambiguous_sidecar"] += 1
                continue
            epoch = capture_time(matches[0])
            if epoch is None:
                counts["bad_timestamp"] += 1
                continue
            st = target.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                counts["nonregular_or_hardlinked"] += 1
                continue
            desired = epoch * 1000000000
            if abs(st.st_mtime_ns - desired) <= 60 * 1000000000:
                counts["already_correct"] += 1
                continue
            rows.append({
                "rel": target.relative_to(ROOT).as_posix(),
                "dev": st.st_dev, "ino": st.st_ino, "size": st.st_size,
                "before": st.st_mtime_ns, "after": desired
            })
    rows.sort(key=lambda row: row["rel"])
    counts["eligible"] = len(rows)
    return rows, counts

def backup():
    """Start a new offsite backup; confirm it covers both photos and journals."""
    unit = "restic-backups-contabo.service"
    active = subprocess.run(["systemctl", "is-active", "--quiet", unit],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if active.returncode == 0:
        raise RuntimeError("Backup unit running already")
    began = time.time()
    subprocess.run(["systemctl", "start", unit], check=True, timeout=7200)
    result = subprocess.run(["systemctl", "show", unit, "--value", "-p", "Result"],
                            capture_output=True, text=True, check=True, timeout=30)
    if result.stdout.strip() != "success":
        raise RuntimeError("Backup unit did not report success")
    runner = Path("/run/current-system/sw/bin/restic-contabo")
    if not runner.is_file():
        found = shutil.which("restic-contabo")
        if not found:
            raise RuntimeError("Missing Restic snapshot inspection wrapper")
        runner = Path(found)
    query = subprocess.run([str(runner), "snapshots", "--json"],
                           check=True, capture_output=True, text=True, timeout=180)
    snapshots = json.loads(query.stdout)
    if not isinstance(snapshots, list):
        raise RuntimeError("Snapshot listing not an array")
    valid = []
    for snap in snapshots:
        try:
            ts = datetime.fromisoformat(snap["time"].replace("Z", "+00:00"))
            paths = set(snap["paths"])
            ident = snap["id"]
            if (ts.tzinfo and began - 60 <= ts.timestamp() <= time.time() + 60
                    and {"/var/lib/nextcloud", "/var/lib/migration-queue"} <= paths
                    and re.fullmatch(r"[0-9a-f]{32,64}", ident)):
                valid.append((ts.timestamp(), ident))
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
    if not valid:
        raise RuntimeError("A fresh Restic snapshot covering photos and journal could not be verified")
    return max(valid)[1]

def new_journal(snapshot, total, selected):
    oldmask = os.umask(0o077)
    try:
        JOURNALS.mkdir(parents=True, mode=0o700, exist_ok=True)
        folder = JOURNALS / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") +
                             "-" + uuid.uuid4().hex[:12])
        folder.mkdir(mode=0o700)
        with (folder / "manifest.json").open("x", encoding="utf-8") as fd:
            json.dump({"format": 1, "root": str(ROOT), "snapshot": snapshot,
                       "total": total, "selected": selected}, fd)
            fd.write("\n")
            fd.flush()
            os.fsync(fd.fileno())
        return folder
    finally:
        os.umask(oldmask)

def protected_open(record):
    path = ROOT / record["rel"]
    if not path.parent.resolve().is_relative_to(ROOT):
        raise RuntimeError("Photo path escaped canonical directory")
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    st = os.fstat(fd)
    if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or
            st.st_dev != record["dev"] or st.st_ino != record["ino"] or
            st.st_size != record["size"]):
        os.close(fd)
        raise RuntimeError("File identity changed; stop for review")
    return fd, st

def scoped_scan():
    subprocess.run([str(OCC), "files:scan", f"--path={OCC_PATH}"],
                   check=True, timeout=3600)

def apply(rows, limit):
    check_root(True)
    batch = rows if limit == 0 else rows[:limit]
    if not batch:
        print("No eligible changes", flush=True)
        return
    print("Running and verifying fresh encrypted Restic backup...", flush=True)
    snap = backup()
    folder = new_journal(snap, len(rows), len(batch))
    print("Snapshot verified: " + snap[:12], flush=True)
    print("Rollback journal: " + str(folder), flush=True)
    changes = 0
    with (folder / "changes.jsonl").open("x", encoding="utf-8") as log:
        for record in batch:
            fd, st = protected_open(record)
            try:
                if st.st_mtime_ns != record["before"]:
                    raise RuntimeError("File mtime changed after inventory")
                # Write-ahead journal; interrupted entries are safe to roll back.
                log.write(json.dumps(record, separators=(",", ":")) + "\n")
                log.flush()
                os.fsync(log.fileno())
                os.utime(fd, ns=(st.st_atime_ns, record["after"]))
                if os.fstat(fd).st_mtime_ns != record["after"]:
                    raise RuntimeError("File did not accept exact mtime")
                changes += 1
            finally:
                os.close(fd)
    print("Changed Files mtimes: " + str(changes), flush=True)
    scoped_scan()
    print("Scoped Nextcloud file cache updated. Image bytes, EXIF and GPS untouched.", flush=True)
    print("Rollback journal retained: " + str(folder), flush=True)

def rollback(path):
    check_root(True)
    if path.is_symlink():
        raise RuntimeError("Rollback journal symlink refused")
    folder = path.resolve()
    if folder.parent != JOURNALS:
        raise RuntimeError("Journal outside protected directory")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != 1 or manifest.get("root") != str(ROOT):
        raise RuntimeError("Journal root or format mismatch")
    with (folder / "changes.jsonl").open(encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream if line.strip()]
    restored, unchanged = 0, 0
    for record in reversed(records):
        fd, st = protected_open(record)
        try:
            if st.st_mtime_ns == record["before"]:
                unchanged += 1
                continue
            if st.st_mtime_ns != record["after"]:
                raise RuntimeError("File changed after repair; manual rollback required")
            os.utime(fd, ns=(st.st_atime_ns, record["before"]))
            restored += 1
        finally:
            os.close(fd)
    print(f"Restored: {restored}; already original: {unchanged}", flush=True)
    scoped_scan()
    print("Rollback complete; journal preserved.", flush=True)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=20,
                    help="number of changed files; 0 means all")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rollback", type=Path)
    ap.add_argument("--confirm", default="")
    a = ap.parse_args()
    if a.limit < 0 or a.limit > 100000 or (a.apply and a.rollback):
        ap.error("Invalid limit or conflicting modes")
    if a.rollback:
        if a.confirm != "ROLLBACK-PHOTO-MTIMES":
            ap.error("Rollback needs --confirm ROLLBACK-PHOTO-MTIMES")
        rollback(a.rollback)
        return
    check_root(a.apply)
    rows, counts = inventory()
    print("=== PHOTO MTIME REPAIR PLAN ===", flush=True)
    for key in ("media", "eligible", "already_correct", "missing_or_ambiguous_sidecar",
                "bad_timestamp", "unsafe_files", "nonregular_or_hardlinked"):
        print(f"{key}: {counts[key]}", flush=True)
    print("Selected: " + str(len(rows) if a.limit == 0 else min(len(rows), a.limit)),
          flush=True)
    if not a.apply:
        print("READ ONLY. No backup or mutation performed.", flush=True)
        return
    if a.confirm != "APPLY-PHOTO-MTIMES":
        ap.error("Apply needs --confirm APPLY-PHOTO-MTIMES")
    apply(rows, a.limit)

if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as exc:
        print(f"STOP: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("No archive/quarantine removed. Retain any journal; re-scan may be needed.",
              file=sys.stderr)
        sys.exit(2)
