#!/usr/bin/env python3
"""Fail-closed one-shot dependency queue for a Discord -> Photos migration.

No NixOS switch, mail service enablement, DNS edit, bridge login or account
deletion is performed. Run explicitly under a supervised systemd transient
service. Disk state is durable; rerun after reboot.
"""
import argparse
import fcntl
import hashlib
import json
import os
import shutil
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

import photo_reconcile
import importlib.util

_recovery_spec = importlib.util.spec_from_file_location("hash_recovery", Path(__file__).parent / "migration-queue" / "hash-recovery.py")
hash_recovery = importlib.util.module_from_spec(_recovery_spec)
_recovery_spec.loader.exec_module(hash_recovery)
_scope_spec = importlib.util.spec_from_file_location("discord_scope", Path(__file__).parent / "discord-archive" / "scope.py")
discord_scope = importlib.util.module_from_spec(_scope_spec)
_scope_spec.loader.exec_module(discord_scope)

STATE = Path("/var/lib/migration-queue")
DB = Path("/var/lib/discord-archive/archive.sqlite")
MANIFEST = STATE / "photos-manifest.json"
MARK = STATE / "photos-migrated.json"
INDEX_MARK = STATE / "photos-indexed.json"
CLEANUP_MARK = STATE / "photos-quarantine-cleaned.json"
PARTIAL = STATE / "discord-partial-approved.json"
POST = STATE / "services-staged.json"
UPLOAD_OBS = STATE / "photos-upload-observation.json"
QUARANTINE = STATE / "photos-duplicate-quarantine"
REPAIR_MARK = STATE / "photos-reconciled.json"
FOLDER = "Photos/Google Photos"
REPO = Path("/etc/nixos")
# NixOS installs a preconfigured Nextcloud OCC wrapper in the system profile.
# The transient unit runs inside `nix shell`, whose PATH can omit this wrapper.
OCC = "/run/current-system/sw/bin/nextcloud-occ"


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".new")
    with open(tmp, "w", encoding="utf-8") as out:
        json.dump(data, out, indent=2, sort_keys=True)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def matrix_notify(event, body):
    """Best-effort private Matrix alert, deduplicated across queue restarts."""
    secret = Path("/var/lib/secrets/matrix-alerts.json")
    try:
        if not secret.is_file():
            return
        marker = STATE / ("matrix-alert-" + event + ".json")
        if marker.exists():
            return
    except (OSError, PermissionError):
        # Unprivileged tests and systems without readable credentials must
        # never have migration blocked by an optional notification feature.
        return
    try:
        cmd = [sys.executable, str(REPO / "hosts/contabo/matrix-alert.py"), body]
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=25)
        atomic_json(marker, {"sent_at": now(), "event": event})
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as err:
        # Alert delivery failure must never corrupt or block photo migration.
        print(f"Matrix notification failed for {event}: {type(err).__name__}", flush=True)


# Task progress notifications are monotone deciles (10,20,...,100).
# A task's 100% means its checkpoint was actually completed, never inferred
# merely from file counts while validation is pending.
PROGRESS_MARK = STATE / "matrix-progress.json"

def progress_notify(task, complete, total, *, done=False, step=10):
    if total <= 0:
        return
    pct = 100 if done else min(99 if step == 1 else 90, (max(0, complete) * 100 // total // step) * step)
    if pct < 10:
        return
    try:
        history = json.loads(PROGRESS_MARK.read_text(encoding="utf-8")) if PROGRESS_MARK.exists() else {}
    except (OSError, ValueError, PermissionError):
        history = {}
    prev = int(history.get(task, 0))
    if pct <= prev:
        return
    # On 1%-granularity tasks, emit each newly crossed percentage.
    # 100% is reserved for verified completion, not an intermediate counter.
    secret = Path("/var/lib/secrets/matrix-alerts.json")
    try:
        if not secret.is_file():
            return
    except (OSError, PermissionError):
        return
    levels = range(prev + 1, pct + 1) if step == 1 else [pct]
    for level in levels:
        body = f"{task}: {level}%"
        try:
            subprocess.run([sys.executable, str(REPO / "hosts/contabo/matrix-alert.py"), body],
                           check=True, capture_output=True, text=True, timeout=25)
            history[task] = level
            atomic_json(PROGRESS_MARK, history)
            print(f"Matrix progress: {body}", flush=True)
        except (OSError, PermissionError, subprocess.CalledProcessError,
                subprocess.TimeoutExpired) as err:
            print(f"Matrix progress delivery failed for {task}: {type(err).__name__}", flush=True)
            break

def discord_progress():
    """Report 1% steps across historical backfill and refresh.

    Work units are two passes per discovered channel. This is progress
    through the currently known set, NOT an ETA or proof of completeness;
    discovery may add channels during collection.
    """
    if not DB.is_file():
        return
    try:
        uri = "file:" + str(DB.absolute()) + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            rows = discord_scope.selected_rows(conn)
            total = len(rows)
            backfilled = sum(r["complete"] == 1 for r in rows)
            refreshed = sum(r["complete"] == 1 and r["refresh_active"] == 0 and r["refreshed_at"] is not None and r["error"] is None for r in rows)
            conn.close()
        progress_notify("Discord archive", backfilled + refreshed, 2 * total, step=1)
    except sqlite3.Error:
        pass


def overall_progress(*, discord_ready=False, photos_ready=False):
    # Weighted milestones; unlike task-level partial counts, overall progress
    # advances only on durable, verified completion of each phase.
    points = (20 if discord_ready else 0) + (20 if photos_ready else 0)
    points += 20 if REPAIR_MARK.exists() else 0
    points += 20 if MARK.exists() else 0
    points += 10 if INDEX_MARK.exists() else 0
    points += 10 if POST.exists() else 0
    progress_notify("Overall migration", points, 100, done=POST.exists())


def discord_running():
    """Treat a still-running collector (possibly tmux-detached) as busy."""
    me = os.getpid()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal() or int(proc.name) == me:
            continue
        try:
            args = (proc / "cmdline").read_bytes().decode("utf-8", "replace").split("\0")
        except (OSError, PermissionError):
            continue
        if any(str(a).endswith("/collector.py") for a in args) and "run" in args:
            return True
    return False


def discord_status(db_path=DB):
    if discord_running():
        return False, "collector.py is still running"
    if not db_path.exists():
        return False, "Discord archive DB absent"
    if db_path == DB and PARTIAL.is_file():
        try:
            record = json.loads(PARTIAL.read_text(encoding="utf-8"))
            if record.get("approved") is True and record.get("archive") == str(DB):
                return True, "PARTIAL DISCORD ARCHIVE manually accepted: " + str(record.get("reason"))
        except (OSError, ValueError):
            pass
    try:
        # SQLite read-only respects WAL and in-progress commits.
        uri = "file:" + str(db_path.absolute()) + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as db:
            rows = discord_scope.selected_rows(db)
            n = len(rows)
            if n == 0:
                return False, "no selected conversations archived"
            pending = sum(r["complete"] != 1 or r["refresh_active"] != 0 or r["refreshed_at"] is None or r["error"] is not None for r in rows)
            if pending:
                return False, f"{pending} selected conversation(s) incomplete or unrefreshed"
            parents = discord_scope.selected_parent_ids(db)
            bad_scans = [r[0] for r in db.execute("SELECT scope FROM scans WHERE ok != 1") if discord_scope.selected_scan(r[0], parents)]
            if bad_scans:
                return False, "incomplete discovery in selected scope: " + ", ".join(bad_scans[:5])
            known_scans = {x[0] for x in db.execute("SELECT scope FROM scans WHERE ok=1")}
            if not {"dms", "guilds", f"guild:{discord_scope.TARGET_GUILD}"} <= known_scans:
                return False, "DM or target guild discovery never succeeded"
            return True, f"{n} registered Discord channels finished"
    except sqlite3.Error as exc:
        return False, f"Discord DB unreadable: {exc}"


def build_manifest(root):
    """Run on local exported Google Photos directory BEFORE deleting Takeout."""
    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Manifest root must be a directory")
    files = {}
    for base, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(base) / d).is_symlink())
        for name in sorted(names):
            p = Path(base) / name
            if p.is_symlink() or not p.is_file():
                raise ValueError(f"Unsafe symlink or non-file in Takeout: {p}")
            rel = p.relative_to(root).as_posix()
            sha = hashlib.sha256()
            with p.open("rb") as src:
                for chunk in iter(lambda: src.read(4 * 1024 * 1024), b""):
                    sha.update(chunk)
            files[rel] = {"size": p.stat().st_size, "sha256": sha.hexdigest()}
    if not files:
        raise ValueError("Takeout directory is empty")
    return {"format": 1, "created": now(), "files": files}


def validate_manifest(manifest, photo_dir):
    if manifest.get("format") != 1 or not isinstance(manifest.get("files"), dict):
        return False, "invalid photo manifest"
    originals = manifest["files"]
    if not originals:
        return False, "empty photo manifest"
    root = Path(photo_dir)
    if not root.is_dir() or root.is_symlink():
        return False, f"uploaded folder absent: {root}"
    found = set()
    for base, dirs, names in os.walk(root, followlinks=False):
        if any((Path(base) / d).is_symlink() for d in dirs):
            return False, "symlink in uploaded folder"
        for name in names:
            p = Path(base) / name
            if not p.is_file() or p.is_symlink():
                return False, "non-file in uploaded folder"
            rel = p.relative_to(root).as_posix()
            found.add(rel)
            meta = originals.get(rel)
            if meta is None:
                return False, f"unexpected file: {rel}"
            if not isinstance(meta, dict) or p.stat().st_size != meta.get("size"):
                return False, f"missing/incomplete file: {rel}"
            digest = hashlib.sha256()
            with p.open("rb") as fh:
                for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != meta.get("sha256"):
                return False, f"content mismatch: {rel}"
    missing = originals.keys() - found
    if missing:
        return False, f"{len(missing)} Takeout file(s) not uploaded, e.g. {next(iter(missing))}"
    return True, f"{len(found)} files exactly matched including SHA-256"


def nc_data_dir():
    result = subprocess.run(
        [OCC, "config:system:get", "datadirectory"],
        check=True, capture_output=True, text=True, timeout=60)
    folder = result.stdout.strip()
    if not folder.startswith("/"):
        raise RuntimeError(f"Unexpected Nextcloud data directory: {folder}")
    return Path(folder).resolve(strict=True)


def nc_photo_dir():
    data = nc_data_dir()
    path = (data / "wug" / "files" / FOLDER).resolve()
    if not path.is_relative_to(data / "wug" / "files"):
        raise RuntimeError("Upload path escaped Nextcloud user files")
    return path


def photos_status(manifest_path=MANIFEST, photo_dir=None):
    if not manifest_path.is_file():
        return False, "Missing local Takeout manifest (see README)"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return validate_manifest(data, photo_dir or nc_photo_dir())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as err:
        return False, f"Photo verification failed: {err}"


def prepare_photos():
    """Reconcile verified Takeout originals independent of folder layout.

    Missing JSON sidecars remain missing *only when listed in the original
    manifest*. Never invent them for older photos. If any original content
    is unavailable, wait for a selective reupload, not a destructive merge.
    """
    if MARK.exists() and REPAIR_MARK.exists():
        # Memories may modify EXIF after migration: the original SHA-256 manifest
        # is no longer a valid test for a legitimately migrated library.
        return True, "Reconciled Takeout; Google metadata migration checkpoint present"
    if REPAIR_MARK.exists():
        return photos_status()
    if not MANIFEST.is_file():
        return False, "Missing original Takeout manifest"
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        originals = manifest["files"]
        root = nc_photo_dir()
        result = hash_recovery.inventory(root, originals)
    except (OSError, ValueError, RuntimeError, KeyError) as err:
        return False, f"Photo audit cannot proceed: {err}"
    progress_notify("Google Photos upload", len(originals) - len(result["missing"]), len(originals), done=result["ok"])
    if not result["ok"]:
        UPLOAD_OBS.unlink(missing_ok=True)
        return False, f"{len(result['missing'])} Takeout files unavailable by SHA-256; use export-missing.py"
    stable, why = photo_reconcile.stable_observation(result, UPLOAD_OBS)
    if not stable:
        return False, why
    subprocess.run(["systemctl", "start", "restic-backups-contabo.service"], check=True)
    again = hash_recovery.inventory(root, originals)
    if not again["ok"] or again["fingerprint"] != result["fingerprint"]:
        UPLOAD_OBS.unlink(missing_ok=True)
        return False, "Upload changed during backup; deferred reconciliation"
    outcomes = hash_recovery.restore(root, originals, QUARANTINE)
    subprocess.run([OCC, "files:scan", f"--path=/wug/files/{FOLDER}"], check=True)
    good, reason = photos_status()
    if not good:
        raise RuntimeError(f"Reconciliation did not pass canonical verification: {reason}")
    atomic_json(REPAIR_MARK, {"finished": now(), "result": outcomes, "verified": reason})
    progress_notify("Google Photos reconciliation", 1, 1, done=True)
    print(f"Reconciled Takeout: {outcomes}, {reason}", flush=True)
    matrix_notify("photos-reconciled", "[Contabo] Google Photos upload fully verified and reconciled.")
    return True, reason


def photos_migrate():
    if not MARK.exists():
        okay, why = photos_status()
        if not okay:
            raise RuntimeError(f"Upload no longer verified: {why}")
        # This backup MUST succeed before mutating uploaded originals.
        print("Starting encrypted offsite backup before EXIF changes...", flush=True)
        subprocess.run(["systemctl", "start", "restic-backups-contabo.service"], check=True)
        # Double-check after backup; concurrent uploads must not change inputs.
        okay, why = photos_status()
        if not okay:
            raise RuntimeError(f"Upload changed during backup: {why}")
        print("Migrating Google Takeout metadata...", flush=True)
        subprocess.run([OCC, "memories:migrate-google-takeout",
                        "--user=wug", f"--folder={FOLDER}"], check=True)
        atomic_json(MARK, {"finished": now(), "input": str(MANIFEST), "files_checked": why})
        progress_notify("Google Photos metadata migration", 1, 1, done=True)
        matrix_notify("photos-migrated", "[Contabo] Google Takeout metadata migration completed.")
    if not INDEX_MARK.exists():
        print("Indexing photos in Nextcloud Memories...", flush=True)
        subprocess.run([OCC, "memories:index", "--user=wug",
                        f"--path={FOLDER}", "--force"], check=True)
        atomic_json(INDEX_MARK, {"finished": now(), "photos_migrated": str(MARK)})
        progress_notify("Memories indexing", 1, 1, done=True)
        matrix_notify("photos-indexed", "[Contabo] Google Photos Memories indexing completed.")



def cleanup_quarantine():
    """Remove quarantined uploads only after indexing and a covered fresh backup.

    A pre-reconciliation snapshot is insufficient. A fresh snapshot must include
    BOTH the Nextcloud user data and the quarantined originals. Otherwise the
    original upload evidence remains recoverable on disk.
    """
    if CLEANUP_MARK.exists():
        return True
    if not REPAIR_MARK.is_file() or not MARK.is_file() or not INDEX_MARK.is_file():
        return False
    if not QUARANTINE.exists():
        # Never infer successful cleanup merely from an absent directory.
        print("Quarantine absent without cleanup checkpoint; manual review needed", flush=True)
        return False
    if QUARANTINE.is_symlink() or not QUARANTINE.is_dir():
        raise RuntimeError("Unsafe quarantine path")
    # Protect a restored canonical directory from accidental deletion.
    root = nc_photo_dir()
    if QUARANTINE.resolve() == root.resolve() or QUARANTINE.resolve().is_relative_to(root.resolve()):
        raise RuntimeError("Quarantine unexpectedly inside photo directory")
    # Check the canonical count and repair checkpoint without demanding the
    # original hashes again: the metadata migration can legitimately alter EXIF.
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if len(manifest["files"]) != int(json.loads(REPAIR_MARK.read_text(encoding="utf-8"))["verified"].split(" files")[0]):
        raise RuntimeError("Reconciliation checkpoint and manifest disagree")
    if sum(1 for p in root.rglob("*") if p.is_file()) != len(manifest["files"]):
        raise RuntimeError("Photo count changed after reconciliation; cannot clean quarantine")

    # The backup unit is a blocking oneshot; starting it waits for completion.
    subprocess.run(["systemctl", "start", "restic-backups-contabo.service"], check=True)
    result = subprocess.run(["restic-contabo", "snapshots", "--json"],
                            check=True, capture_output=True, text=True, timeout=120)
    snapshots = json.loads(result.stdout)
    checkpoint_time = datetime.fromisoformat(json.loads(INDEX_MARK.read_text(encoding="utf-8"))["finished"])
    valid = False
    for snapshot in snapshots:
        try:
            created = datetime.fromisoformat(snapshot["time"].replace("Z", "+00:00"))
            paths = set(snapshot["paths"])
            if (created > checkpoint_time and "/var/lib/nextcloud" in paths
                    and "/var/lib/migration-queue" in paths):
                valid = True
                break
        except (KeyError, ValueError, TypeError):
            continue
    if not valid:
        print("Quarantine cleanup deferred: no post-indexing Restic snapshot containing "
              "both /var/lib/nextcloud and /var/lib/migration-queue. "
              "Retaining all quarantine files.", flush=True)
        return False
    # The directory contains only misplaced copies, not canonical Takeout paths.
    shutil.rmtree(QUARANTINE)
    atomic_json(CLEANUP_MARK, {"finished": now(),
              "reason": "post-indexing covered Restic snapshot; canonical files retained"})
    matrix_notify("photos-quarantine-cleaned",
                  "[Contabo] Verified photo quarantine cleanup complete; space reclaimed.")
    print("Photo quarantine cleaned after fresh covered backup.", flush=True)
    return True

def stage_services():
    if POST.exists():
        return
    # DO NOT change the live NixOS generation. These run offline preflights.
    logfile = STATE / "service-readiness.log"
    commands = [
        ["bash", str(REPO / "hosts/contabo/mail-server/preflight.sh")],
        ["bash", str(REPO / "hosts/contabo/evaluate-future-bridges.sh")],
    ]
    results = []
    with logfile.open("a", encoding="utf-8") as out:
        for cmd in commands:
            out.write("$ " + " ".join(cmd) + "\n")
            out.flush()
            proc = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT,
                                  timeout=1800, check=False)
            results.append({"command": cmd, "returncode": proc.returncode})
            if proc.returncode != 0:
                break
    # Never record readiness as successful after a failed evaluation.
    if any(result["returncode"] != 0 for result in results):
        raise RuntimeError(f"Post-migration preflight failed; see {logfile}")
    atomic_json(POST, {"checked": now(), "results": results,
                        "mail_enabled": False, "bridges_enabled": False,
                        "next": "Review DNS, secrets, auth, and switch manually"})
    progress_notify("Service preflight", 1, 1, done=True)
    print(f"Service readiness staged: {POST}, log: {logfile}")
    matrix_notify("migration-complete", "[Contabo] Photo migration and preflight steps completed. Mail and messaging bridges remain disabled pending review.")


def status():
    d = discord_status()
    p = photos_status()
    print(json.dumps({"discord": {"ready": d[0], "reason": d[1]},
                      "photos": {"ready": p[0], "reason": p[1]},
                      "reconciliation_done": REPAIR_MARK.exists(),
                      "migration_done": MARK.exists(),
                      "index_done": INDEX_MARK.exists(),
                      "services_staged": POST.exists()}, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)
    man = sub.add_parser("manifest")
    man.add_argument("source", help="local Google Photos Takeout directory")
    man.add_argument("output", help="manifest output file")
    sub.add_parser("status")
    partial = sub.add_parser("approve-partial-discord")
    partial.add_argument("--reason", required=True, help="human-readable reason for accepting incomplete history")
    run = sub.add_parser("run")
    run.add_argument("--interval", type=int, default=600)
    args = ap.parse_args()
    if args.action == "manifest":
        atomic_json(Path(args.output).expanduser(), build_manifest(args.source))
        print(f"Saved manifest: {args.output}")
        return
    if args.action == "status":
        status()
        return
    if args.action == "approve-partial-discord":
        if os.geteuid() != 0:
            ap.error("approval must be made by root on Contabo")
        if discord_running():
            raise RuntimeError("Collector is still running; cannot approve partial archive yet")
        if not DB.is_file():
            raise RuntimeError("No Discord archive to approve")
        reason = args.reason.strip()
        if len(reason) < 12:
            raise ValueError("Please specify a meaningful reason (at least 12 characters)")
        print("WARNING: Discord archive is NOT complete; missing conversations may be permanent.")
        print("The queue will proceed to Photos migration, but cannot certify Discord history.")
        if input('Type exactly "ACCEPT INCOMPLETE DISCORD" to continue: ') != "ACCEPT INCOMPLETE DISCORD":
            raise RuntimeError("Partial-archive approval cancelled")
        atomic_json(PARTIAL, {"approved": True, "archive": str(DB),
                              "reason": reason, "approved_at": now()})
        print(f"Recorded an explicit, auditable partial-archive exception in {PARTIAL}")
        return
    if os.geteuid() != 0:
        ap.error("run must execute as root for Nextcloud/Restic filesystem access")
    if args.interval < 60:
        ap.error("minimum interval 60 seconds")
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(STATE / "queue.lock", "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another migration queue is already running")
        while True:
            # Photos are independent of Discord. The verified reconciliation
            # checkpoint is sufficient to start metadata import and indexing.
            p = prepare_photos()
            if p[0]:
                photos_migrate()
                if INDEX_MARK.exists() and not CLEANUP_MARK.exists():
                    # Cleanup is optional and fail-closed; it must never block
                    # successfully indexed photos or ongoing Discord collection.
                    cleanup_quarantine()

            d = discord_status()
            if d[0]:
                progress_notify("Discord archive", 1, 1, done=True)
            else:
                discord_progress()
            overall_progress(discord_ready=d[0], photos_ready=p[0])
            if INDEX_MARK.exists() and d[0]:
                stage_services()
                overall_progress(discord_ready=True, photos_ready=True)
                if CLEANUP_MARK.exists():
                    print("Queued work finished. No NixOS switch was performed.", flush=True)
                    return
            if not p[0]:
                print(f"{now()} Awaiting photos: {p[1]}", flush=True)
            if not d[0]:
                print(f"{now()} Awaiting Discord: {d[1]}", flush=True)
            # Poll Discord cheaply every minute without rehashing photos.
            for _ in range(0, args.interval, 60):
                time.sleep(min(60, args.interval))
                if not discord_running():
                    break
                discord_progress()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, sqlite3.Error, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, ValueError) as exc:
        matrix_notify("queue-failed", "[Contabo] Migration queue failed and needs review. Check journalctl -u discord-photos-queue.")
        print(f"QUEUE FAILED (safe to retry): {exc}", file=sys.stderr)
        sys.exit(1)
