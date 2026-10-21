#!/usr/bin/env python3
"""Inventory and optionally purge rooms created by the old Discord bridge.

Read-only by default. Uses the old bridge SQLite DB as an allowlist so it
cannot accidentally target unrelated Matrix rooms. Does not modify Discord.
"""
import argparse
import getpass
import json
from pathlib import Path
import sqlite3
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

SYNAPSE = "http://127.0.0.1:8008"


def rooms_from_database(db_path):
    if not db_path.is_file():
        raise RuntimeError(f"Bridge database missing: {db_path}")
    uri = "file:" + quote(str(db_path.absolute()), safe="/") + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    try:
        targets = set()
        queries = [
            'SELECT mxid FROM portal WHERE mxid IS NOT NULL',
            'SELECT mxid FROM guild WHERE mxid IS NOT NULL',
            'SELECT management_room FROM "user" WHERE management_room IS NOT NULL',
            'SELECT space_room FROM "user" WHERE space_room IS NOT NULL',
            'SELECT dm_space_room FROM "user" WHERE dm_space_room IS NOT NULL',
        ]
        for query in queries:
            try:
                targets.update(str(r[0]) for r in db.execute(query)
                               if r[0] and str(r[0]).startswith("!") and
                               str(r[0]).endswith(":iniyanjoseph.com"))
            except sqlite3.OperationalError as err:
                # A missing expected table is a schema mismatch, not proof
                # that the corresponding rooms don't exist.
                raise RuntimeError(f"Cannot inventory bridge rooms: {err}") from err
        return sorted(targets)
    finally:
        db.close()


def api_request(token, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(SYNAPSE + path, data=data, method=method, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    })
    with urlopen(req, timeout=60) as response:
        return json.loads(response.read())


def purge(token, room):
    path = "/_synapse/admin/v2/rooms/" + quote(room, safe="")
    try:
        result = api_request(token, "DELETE", path, {"purge": True, "block": False})
    except HTTPError as exc:
        if exc.code == 404:
            return "already absent"
        raise
    delete_id = result.get("delete_id")
    if not delete_id:
        raise RuntimeError(f"No delete_id for {room}: {result}")
    for attempt in range(720):
        status = api_request(token, "GET",
            "/_synapse/admin/v2/rooms/delete_status/" + quote(delete_id, safe=""))
        if status.get("status") == "complete":
            return "complete"
        if status.get("status") == "failed":
            raise RuntimeError(f"Deletion failed: {status.get('error')}")
        time.sleep(5)
    raise RuntimeError(f"Timed out waiting for room deletion: {room}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/var/lib/mautrix-discord/mautrix-discord.db")
    ap.add_argument("--manifest", default="/var/lib/discord-archive/old-matrix-rooms.json")
    ap.add_argument("action", choices=["inventory", "purge"])
    args = ap.parse_args()
    source = Path(args.db)
    manifest = Path(args.manifest)
    if args.action == "inventory":
        rooms = rooms_from_database(source)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"rooms": rooms}, indent=2) + "\n")
        manifest.chmod(0o600)
        print(f"Saved {len(rooms)} Discord-associated Matrix room IDs to {manifest}")
        print("Unrelated Matrix rooms are not included.")
        return
    if not manifest.is_file():
        raise RuntimeError("Run inventory first and inspect the manifest")
    stored = json.loads(manifest.read_text())
    rooms = stored.get("rooms")
    if not isinstance(rooms, list) or any(
        not isinstance(r, str) or not r.startswith("!") or
        not r.endswith(":iniyanjoseph.com") for r in rooms):
        raise ValueError("Invalid room manifest")
    print(f"About to permanently purge {len(rooms)} old Discord-associated Matrix rooms.")
    print("This will remove their messages from Synapse, NOT affect WhatsApp/Nextcloud.")
    if input('Type "PURGE DISCORD" to proceed: ') != "PURGE DISCORD":
        raise RuntimeError("Cancelled")
    token = getpass.getpass("Synapse ADMIN access token (hidden): ").strip()
    if not token:
        raise RuntimeError("Admin access token required")
    # Fail before deleting anything if the supplied credential isn't admin.
    api_request(token, "GET", "/_synapse/admin/v1/rooms?limit=1")
    failures = []
    for ix, room in enumerate(rooms, 1):
        try:
            print(f"[{ix}/{len(rooms)}] {room}", flush=True)
            print(" ", purge(token, room), flush=True)
        except (RuntimeError, HTTPError, URLError, ValueError) as err:
            print(f"  FAILED: {err}", file=sys.stderr)
            failures.append(room)
    if failures:
        raise RuntimeError(f"{len(failures)} rooms failed; rerun after resolving errors")
    print("Listed bridge rooms purged. Other bridge ghost users may still exist.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, sqlite3.Error, HTTPError, URLError) as err:
        print("ERROR:", err, file=sys.stderr)
        sys.exit(1)
