#!/usr/bin/env python3
"""Manual, resumable Discord API archive collector (no Matrix writes).

Uses a Discord personal user token, an unsupported self-bot integration that
risks account suspension. Archives private plaintext Discord JSON in SQLite.
"""
import argparse
import datetime as dt
import fcntl
import getpass
import json
import os
from pathlib import Path
import random
import sqlite3
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

API = "https://discord.com/api/v9"
TARGET_GUILD = "804408079940583475"

def selected_scopes(db):
    parents = {r[0] for r in db.execute("SELECT id FROM channels WHERE kind=?", (f"guild:{TARGET_GUILD}",))}
    return parents

def selected_kind(kind, parents):
    return (kind == "dms" or kind in (f"guild:{TARGET_GUILD}", f"threads-active:{TARGET_GUILD}")
            or any(kind == f"archived-{type_}:{pid}" for pid in parents for type_ in ("public","private")))

def selected_channels(db):
    parents = selected_scopes(db)
    return [row for row in db.execute("SELECT * FROM channels ORDER BY id").fetchall()
            if selected_kind(row["kind"], parents)]



def error_summary(status, body, path):
    """Safe diagnostic: never print raw responses or authorization headers."""
    endpoint = path.split("?")[0]
    try:
        payload = json.loads(body)
        if isinstance(payload, dict) and isinstance(payload.get("code"), int):
            return f"HTTP {status}, Discord code {payload['code']}: {endpoint}"
    except (ValueError, UnicodeDecodeError, TypeError):
        pass
    return f"HTTP {status}, non-JSON or unrecognized error response: {endpoint}"


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def connect(path):
    os.umask(0o077)
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path, timeout=60)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    with db:
        db.execute("""CREATE TABLE IF NOT EXISTS channels(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
            before_id TEXT, complete INTEGER NOT NULL DEFAULT 0,
            error TEXT, refresh_floor TEXT, refresh_before TEXT,
            refresh_active INTEGER NOT NULL DEFAULT 0,
            refreshed_at TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS messages(
            channel_id TEXT NOT NULL, id TEXT NOT NULL, json TEXT NOT NULL,
            PRIMARY KEY(channel_id,id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS scans(
            scope TEXT PRIMARY KEY, ok INTEGER NOT NULL,
            count INTEGER NOT NULL, error TEXT, checked_at TEXT NOT NULL)""")
    return db


def credentials():
    token = getpass.getpass("Discord USER token (hidden, not stored): ").strip()
    if not token:
        raise ValueError("Empty token")
    return token


class APIClient:
    def __init__(self, token, delay):
        self.token, self.delay = token, delay

    def get(self, path):
        if not path.startswith("/"):
            raise ValueError("Invalid API path")
        for attempt in range(16):
            cooldown = None
            try:
                req = Request(API + path, headers={
                    "Authorization": self.token,
                    "Accept": "application/json",
                    "User-Agent": "DiscordHistoryArchiver/0.2"})
                with urlopen(req, timeout=60) as response:
                    body = response.read()
                result = json.loads(body)
                time.sleep(self.delay)
                return result
            except HTTPError as err:
                body = err.read(4096)
                detail = error_summary(err.code, body, path)
                if err.code in (400, 401, 403, 404, 405):
                    raise RuntimeError(detail) from None
                if err.code == 429:
                    try:
                        value = json.loads(body)
                        cooldown = max(2.0, float(value.get("retry_after", 20.0)))
                    except (ValueError, TypeError, AttributeError):
                        cooldown = 30.0
                    try:
                        cooldown = max(cooldown, float(err.headers.get("Retry-After", 0)))
                    except (ValueError, TypeError):
                        pass
                elif err.code in (500, 502, 503, 504, 520, 522, 524):
                    cooldown = min(600.0, 2 ** min(attempt + 2, 9))
                else:
                    raise RuntimeError(detail) from None
            except (URLError, TimeoutError, OSError, ValueError):
                # A transient outage or HTML anti-abuse page is not JSON.
                cooldown = min(600.0, 2 ** min(attempt + 2, 9))
            if attempt < 15:
                seconds = min(900, max(self.delay, cooldown or 15.0) + random.random() * 2)
                print(f"API temporarily unavailable, retry {attempt+1}/15 in {seconds:.1f}s", flush=True)
                time.sleep(seconds)
        raise RuntimeError(f"16 API attempts failed: {path.split('?')[0]}")


def record_scope(db, scope, ok, count=0, error=None):
    with db:
        db.execute("""INSERT INTO scans(scope,ok,count,error,checked_at)
            VALUES(?,?,?,?,?) ON CONFLICT(scope) DO UPDATE SET
            ok=excluded.ok,count=excluded.count,error=excluded.error,
            checked_at=excluded.checked_at""",
            (scope, int(ok), count, error, stamp()))


def register(db, objects, kind):
    records = []
    for obj in objects:
        ident = str(obj["id"])
        if not ident.isdecimal():
            raise ValueError("Invalid Discord channel ID")
        records.append((ident, str(obj.get("name") or ident), kind))
    with db:
        db.executemany("""INSERT OR IGNORE INTO channels(id,name,kind)
                           VALUES(?,?,?)""", records)
    return len(records)


def inventory(db, api, scope, url, extract=lambda x: x):
    try:
        response = api.get(url)
        objects = extract(response)
        if not isinstance(objects, list):
            raise ValueError("Invalid API inventory")
        count = register(db, objects, scope)
        record_scope(db, scope, True, count)
        return response
    except KeyboardInterrupt:
        record_scope(db, scope, False, error="interrupted")
        raise
    except Exception as err:
        record_scope(db, scope, False, error=str(err))
        print(f"INCOMPLETE discovery {scope}: {err}", file=sys.stderr)
        return None


def discover(db, api):
    inventory(db, api, "dms", "/users/@me/channels")
    # Guild objects are NOT message channels; record this discovery without
    # inserting guild IDs into the message collection table.
    guilds = inventory(db, api, "guilds", "/users/@me/guilds",
                       extract=lambda x: [] if isinstance(x, list) else None)
    if guilds is None:
        return
    for guild in guilds:
        gid = str(guild["id"])
        if gid != TARGET_GUILD:
            continue
        name = guild.get("name", gid)
        parents = inventory(db, api, f"guild:{gid}", f"/guilds/{gid}/channels",
                            extract=lambda items: [
                                dict(item, name=name + "/" + item.get("name", ""))
                                for item in items if item.get("type") in (0, 5)
                            ] if isinstance(items, list) else None)
        inventory(db, api, f"threads-active:{gid}", f"/guilds/{gid}/threads/active",
                  extract=lambda x: x.get("threads") if isinstance(x, dict) else None)
        if parents is None:
            continue
        for parent in parents:
            if parent.get("type") not in (0, 5, 15, 16):
                continue
            pid = str(parent["id"])
            kinds = [("public", f"/channels/{pid}/threads/archived/public")]
            if parent.get("type") == 0:
                kinds.append(("private", f"/channels/{pid}/users/@me/threads/archived/private"))
            for kind, path in kinds:
                scope = f"archived-{kind}:{pid}"
                before = None
                count = 0
                try:
                    for _ in range(100000):
                        url = path + "?limit=100"
                        if before:
                            url += "&before=" + quote(before, safe="")
                        response = api.get(url)
                        threads = response.get("threads")
                        more = response.get("has_more")
                        if not isinstance(threads, list) or not isinstance(more, bool):
                            raise ValueError("Malformed thread page")
                        count += register(db, threads, scope)
                        if not more:
                            break
                        if not threads:
                            raise ValueError("Empty thread page marked has_more")
                        last = threads[-1]
                        cursor = (str(last["id"]) if kind == "private" else
                                  (last.get("thread_metadata") or {}).get("archive_timestamp"))
                        if not cursor or cursor == before:
                            raise ValueError("Nonadvancing archived-thread cursor")
                        before = cursor
                    else:
                        raise RuntimeError("Archived-thread page budget exhausted")
                    record_scope(db, scope, True, count)
                except Exception as err:
                    record_scope(db, scope, False, count, str(err))
                    print(f"INCOMPLETE {scope}: {err}", file=sys.stderr)
    print("Discovery is NOT exhaustive: dormant DMs and inaccessible threads may be omitted.")


def page_ids(messages, before=None):
    if not isinstance(messages, list):
        raise ValueError("Message API did not return a list")
    ids = [str(x["id"]) for x in messages]
    if len(ids) != len(set(ids)) or not all(x.isdecimal() for x in ids):
        raise ValueError("Invalid or duplicate message ID")
    if any(int(x) <= int(y) for x, y in zip(ids, ids[1:])):
        raise ValueError("API message page is not newest-first")
    if before and any(int(x) >= int(before) for x in ids):
        raise ValueError("History cursor did not advance")
    return ids


def store(db, cid, messages, cursor, *, fresh=False, done=False, floor=None):
    with db:
        db.executemany("""INSERT OR REPLACE INTO messages(channel_id,id,json)
                           VALUES(?,?,?)""",
                       ((cid, str(x["id"]), json.dumps(x, ensure_ascii=False))
                        for x in messages))
        if fresh:
            if done:
                db.execute("""UPDATE channels SET refresh_floor=NULL,refresh_before=NULL,
                    refresh_active=0,refreshed_at=?,error=NULL WHERE id=?""", (stamp(), cid))
            else:
                db.execute("""UPDATE channels SET refresh_floor=?,refresh_before=?,
                    refresh_active=1 WHERE id=?""", (floor, cursor, cid))
        else:
            db.execute("""UPDATE channels SET before_id=?,complete=?,error=NULL
                           WHERE id=?""", (cursor, int(done), cid))


def fetch_history(db, api):
    for channel in (c for c in selected_channels(db) if not c["complete"]):
        cid, before = channel["id"], channel["before_id"]
        print(f"History {channel['name']}: continuing from {before or 'newest'}", flush=True)
        try:
            while True:
                url = f"/channels/{cid}/messages?limit=50"
                if before:
                    url += "&before=" + before
                messages = api.get(url)
                ids = page_ids(messages, before)
                cursor = ids[-1] if ids else before
                store(db, cid, messages, cursor, done=not bool(messages))
                if not messages:
                    break
                before = cursor
        except Exception as err:
            with db:
                db.execute("UPDATE channels SET error=? WHERE id=?", (str(err), cid))
            print(f"INCOMPLETE history {cid}: {err}", file=sys.stderr)


def catch_up(db, api):
    for channel in (c for c in selected_channels(db) if c["complete"]):
        cid = channel["id"]
        if channel["refresh_active"]:
            floor, before = channel["refresh_floor"], channel["refresh_before"]
        else:
            newest = db.execute("""SELECT id FROM messages WHERE channel_id=?
                ORDER BY LENGTH(id) DESC,id DESC LIMIT 1""", (cid,)).fetchone()
            floor = newest["id"] if newest else None
            before = None
            with db:
                db.execute("""UPDATE channels SET refresh_active=1,refresh_floor=?,
                    refresh_before=NULL,refreshed_at=NULL WHERE id=?""", (floor, cid))
        try:
            while True:
                url = f"/channels/{cid}/messages?limit=50"
                if before:
                    url += "&before=" + before
                page = api.get(url)
                ids = page_ids(page, before)
                done = not page or (floor is not None and any(int(x) <= int(floor) for x in ids))
                new = [m for m in page if floor is None or int(m["id"]) > int(floor)]
                store(db, cid, new, ids[-1] if ids else before,
                      fresh=True, done=done, floor=floor)
                if done:
                    break
                before = ids[-1]
        except Exception as err:
            with db:
                db.execute("UPDATE channels SET error=? WHERE id=?", (str(err), cid))
            print(f"INCOMPLETE catch-up {cid}: {err}", file=sys.stderr)


def summary(db):
    selected = {c["id"] for c in selected_channels(db)}
    rows = [r for r in db.execute("""SELECT c.*, (SELECT COUNT(*) FROM messages m
        WHERE m.channel_id=c.id) AS n FROM channels c ORDER BY c.id""").fetchall()
        if r["id"] in selected]
    parents = selected_scopes(db)
    def relevant_scope(scope):
        return (scope in ("dms","guilds",f"guild:{TARGET_GUILD}",f"threads-active:{TARGET_GUILD}")
                or any(scope == f"archived-{kind}:{pid}" for pid in parents for kind in ("public","private")))
    scans = [s for s in db.execute("SELECT * FROM scans ORDER BY scope").fetchall()
             if relevant_scope(s["scope"])]
    issues = [f"{r['id']} {r['name']}: {r['error'] or 'not complete'}" for r in rows
              if not r["complete"] or r["refresh_active"] or not r["refreshed_at"] or r["error"]]
    issues += [f"Discovery {s['scope']}: {s['error']}" for s in scans if not s["ok"]]
    for must in ("dms", "guilds", f"guild:{TARGET_GUILD}"):
        if not any(s["scope"] == must and s["ok"] for s in scans):
            issues.append(f"Missing successful {must} discovery")
    return {
        "timestamp": stamp(),
        "scope": f"All visible DMs and target guild {TARGET_GUILD} only; no other guild history",
        "channels": [dict(r) for r in rows],
        "scans": [dict(r) for r in scans],
        "messages": sum(r["n"] for r in rows),
        "issues": issues,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(Path.home() / ".local/share/discord-archive/archive.sqlite"))
    parser.add_argument("--delay", type=float, default=5.0)
    parser.add_argument("action", choices=["run", "discover", "collect", "refresh", "report", "verify"])
    args = parser.parse_args()
    if args.delay < 1:
        parser.error("Minimum request interval: 1 second")
    path = Path(args.db).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.umask(0o077)
    with open(str(path) + ".lock", "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another archive process is already running")
        db = connect(path)
        if args.action in ("run", "discover", "collect", "refresh"):
            api = APIClient(credentials(), args.delay)
            identity = api.get("/users/@me")
            if not isinstance(identity, dict) or not str(identity.get("id", "")).isdecimal():
                raise RuntimeError("Discord token preflight returned an unexpected user object")
            print("Discord identity request accepted; attempting channel discovery.", flush=True)
            if args.action in ("run", "discover"):
                discover(db, api)
            if args.action in ("run", "collect"):
                fetch_history(db, api)
            if args.action in ("run", "refresh"):
                catch_up(db, api)
        result = summary(db)
        status = path.parent / "status.json"
        status.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps({"channels": len(result["channels"]), "messages": result["messages"],
                          "incomplete": len(result["issues"]),
                          "problems": result["issues"][:12]}, indent=2))
        if args.action in ("verify", "run") and result["issues"]:
            sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
