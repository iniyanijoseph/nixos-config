#!/usr/bin/env python3
"""Send Matrix migration status every 20 minutes while work is unfinished."""
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("matrix_commands", HERE / "matrix-commands.py")
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)

STATE = Path("/var/lib/migration-queue")
CHECKPOINTS = ("photos-reconciled.json", "photos-migrated.json",
               "photos-indexed.json", "photos-quarantine-cleaned.json",
               "services-staged.json")

def finished():
    if not all((STATE / name).is_file() for name in CHECKPOINTS):
        return False
    # Discovery errors and incomplete channel passes prevent declaring done.
    scope = status.DB
    if not scope.is_file():
        return False
    # An in-flight collector can still add messages or discover channels.
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            args = (proc / "cmdline").read_bytes().decode("utf-8", "replace").split("\0")
            if any(str(a).endswith("/collector.py") for a in args) and "run" in args:
                return False
        except (OSError, PermissionError):
            pass
    import sqlite3
    try:
        uri = "file:" + str(scope) + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as db:
            db.row_factory = sqlite3.Row
            rows = status.discord_scope.selected_rows(db)
            if not rows or any(r["complete"] != 1 or r["refresh_active"] != 0
                               or r["refreshed_at"] is None or r["error"] is not None
                               for r in rows):
                return False
            parents = status.discord_scope.selected_parent_ids(db)
            if any(status.discord_scope.selected_scan(r[0], parents)
                   for r in db.execute("SELECT scope FROM scans WHERE ok != 1")):
                return False
            scans = {r[0] for r in db.execute("SELECT scope FROM scans WHERE ok=1")}
            return {"dms", "guilds", f"guild:{status.discord_scope.TARGET_GUILD}"} <= scans
    except sqlite3.Error:
        return False

def main():
    completed = finished()
    if completed and (STATE / "matrix-periodic-final-sent.json").exists():
        return
    message = status.status_text()
    if completed:
        message = "MIGRATION FINISHED — final report\n\n" + message
    else:
        message = "SCHEDULED MIGRATION REPORT (20-minute interval)\n\n" + message
    status.alerts.send(message)
    if completed:
        marker = STATE / "matrix-periodic-final-sent.json"
        marker.write_text(json.dumps({"sent":status.datetime.now(status.timezone.utc).isoformat()})+"\n")
        marker.chmod(0o600)

if __name__ == "__main__":
    main()
