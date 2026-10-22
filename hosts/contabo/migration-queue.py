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
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

STATE = Path("/var/lib/migration-queue")
DB = Path("/var/lib/discord-archive/archive.sqlite")
MANIFEST = STATE / "photos-manifest.json"
MARK = STATE / "photos-migrated.json"
INDEX_MARK = STATE / "photos-indexed.json"
PARTIAL = STATE / "discord-partial-approved.json"
POST = STATE / "services-staged.json"
FOLDER = "Photos/Google Photos"
REPO = Path("/etc/nixos")


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
            n = db.execute("SELECT count(*) FROM channels").fetchone()[0]
            if n == 0:
                return False, "no Discord conversations archived"
            pending = db.execute(
                """SELECT count(*) FROM channels WHERE complete != 1
                   OR refresh_active != 0 OR refreshed_at IS NULL
                   OR error IS NOT NULL"""
            ).fetchone()[0]
            if pending:
                return False, f"{pending} conversation(s) incomplete or unrefreshed"
            bad_scans = db.execute(
                "SELECT scope FROM scans WHERE ok != 1 ORDER BY scope"
            ).fetchall()
            if bad_scans:
                return False, "incomplete discovery: " + ", ".join(x[0] for x in bad_scans[:5])
            known_scans = {x[0] for x in db.execute("SELECT scope FROM scans WHERE ok=1")}
            if not {"dms", "guilds"} <= known_scans:
                return False, "DM or guild discovery never succeeded"
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
        ["nextcloud-occ", "config:system:get", "datadirectory"],
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
        subprocess.run(["nextcloud-occ", "memories:migrate-google-takeout",
                        "--user=wug", f"--folder={FOLDER}"], check=True)
        atomic_json(MARK, {"finished": now(), "input": str(MANIFEST), "files_checked": why})
    if not INDEX_MARK.exists():
        print("Indexing photos in Nextcloud Memories...", flush=True)
        subprocess.run(["nextcloud-occ", "memories:index", "--user=wug",
                        f"--path={FOLDER}", "--force"], check=True)
        atomic_json(INDEX_MARK, {"finished": now(), "photos_migrated": str(MARK)})


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
    print(f"Service readiness staged: {POST}, log: {logfile}")


def status():
    d = discord_status()
    p = photos_status()
    print(json.dumps({"discord": {"ready": d[0], "reason": d[1]},
                      "photos": {"ready": p[0], "reason": p[1]},
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
            d = discord_status()
            if d[0]:
                p = photos_status()
                if p[0] or MARK.exists():
                    print(f"{now()} Both dependency checks passed: {d[1]}; {p[1]}", flush=True)
                    photos_migrate()
                    if INDEX_MARK.exists():
                        stage_services()
                    print("Queued work finished. No NixOS switch was performed.", flush=True)
                    return
                print(f"{now()} Awaiting photos: {p[1]}", flush=True)
            else:
                print(f"{now()} Awaiting Discord: {d[1]}", flush=True)
            time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, sqlite3.Error, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, ValueError) as exc:
        print(f"QUEUE FAILED (safe to retry): {exc}", file=sys.stderr)
        sys.exit(1)
