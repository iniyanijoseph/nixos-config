#!/usr/bin/env python3
"""Sanitized, read-only Discord archive coverage and collector health report.

No authentication, network calls, messages, attachments or private channel
names are emitted. SQLite is opened mode=ro; do not use immutable=1 on a
possibly active WAL database. This does not certify recoverable attachments.
"""
import argparse
from collections import Counter
import importlib.util
import os
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import quote

DB = Path("/var/lib/discord-archive/archive.sqlite")
HERE = Path(__file__).resolve().parent

def status(label, value):
    print(f"{label}: {value}", flush=True)

def running_collectors():
    running = []
    for item in Path("/proc").iterdir():
        if not item.name.isdecimal() or int(item.name) == os.getpid():
            continue
        try:
            args = (item / "cmdline").read_bytes().decode("utf-8", "replace").split("\0")
            if any(Path(arg).name == "collector.py" for arg in args) and "run" in args:
                running.append(int(item.name))
        except (OSError, PermissionError, ValueError):
            pass
    return running

def age_seconds(st):
    return max(0, int(__import__("time").time() - st.st_mtime))

def category(kind):
    kind = kind or ""
    if kind == "dms":
        return "DMs"
    if kind.startswith("guild:"):
        return "Guild channels"
    if kind.startswith("threads-active:"):
        return "Active threads"
    if kind.startswith("archived-public:"):
        return "Archived public threads"
    if kind.startswith("archived-private:"):
        return "Archived private threads"
    return "Other archived discovery"

def category_scan(name):
    return category(name) if name not in ("guilds",) else "Guild enumeration"

def deep_audit(db, ids):
    """Stream archived JSON without printing author IDs, bodies or URLs."""
    print("DEEP AUDIT: scanning archived message metadata; no network or writes", flush=True)
    counts = Counter()
    message_types = Counter()
    total_attachment_bytes = 0
    for start in range(0, len(ids), 400):
        batch = ids[start:start + 400]
        if not batch:
            continue
        q = ",".join("?" for _ in batch)
        cursor = db.execute(
            f"SELECT json FROM messages WHERE channel_id IN ({q})", batch
        )
        for (raw,) in cursor:
            counts["rows"] += 1
            try:
                obj = __import__("json").loads(raw)
                if not isinstance(obj, dict):
                    counts["invalid_json"] += 1
                    continue
            except (ValueError, TypeError):
                counts["invalid_json"] += 1
                continue
            message_types[str(obj.get("type", "unspecified"))] += 1
            if not isinstance(obj.get("author"), dict):
                counts["missing_author"] += 1
            if not isinstance(obj.get("content"), str) or not obj["content"]:
                counts["empty_or_missing_content"] += 1
            attachments = obj.get("attachments")
            if attachments is not None and not isinstance(attachments, list):
                counts["invalid_attachments_type"] += 1
                attachments = []
            if attachments:
                counts["messages_with_attachment_metadata"] += 1
                counts["attachment_references"] += len(attachments)
                for a in attachments:
                    if not isinstance(a, dict):
                        counts["invalid_attachment_entries"] += 1
                        continue
                    size = a.get("size")
                    if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
                        total_attachment_bytes += size
                    if not a.get("url"):
                        counts["attachment_missing_source_url"] += 1
            for field, label in (
                ("embeds", "messages_with_embeds"),
                ("reactions", "messages_with_reactions"),
                ("sticker_items", "messages_with_stickers"),
            ):
                value = obj.get(field)
                if isinstance(value, list) and value:
                    counts[label] += 1
            if obj.get("edited_timestamp"):
                counts["messages_with_edit_timestamp"] += 1
            if obj.get("message_reference") or obj.get("referenced_message"):
                counts["messages_with_reply_reference"] += 1
            if counts["rows"] % 200000 == 0:
                print(f"Deep scan progress: {counts['rows']} records", flush=True)
    print("=== STORED SOURCE METADATA (NO TEXT OR MEDIA) ===")
    for field in (
        "rows", "invalid_json", "missing_author", "empty_or_missing_content",
        "messages_with_attachment_metadata", "attachment_references",
        "invalid_attachments_type", "invalid_attachment_entries",
        "attachment_missing_source_url", "messages_with_embeds",
        "messages_with_reactions", "messages_with_stickers",
        "messages_with_edit_timestamp", "messages_with_reply_reference",
    ):
        print(f"{field}: {counts[field]}", flush=True)
    print(f"Declared attachment bytes (not downloaded bytes): {total_attachment_bytes}", flush=True)
    print("Source message type distribution: " +
          ", ".join(f"{kind}={number}" for kind, number in
                    sorted(message_types.items(), key=lambda item: item[0])), flush=True)
    print("Attachment media present on disk: NOT VERIFIED", flush=True)
    print("Messages converted to native Matrix events: NOT VERIFIED", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deep", action="store_true",
                        help="read every selected message JSON and report media/reply/edit aggregates")
    args = parser.parse_args()
    status("Mode", "read-only, sanitized; no NixOS/Matrix/Discord changes")
    found = running_collectors()
    status("Collector processes", len(found))
    if not DB.is_file() or DB.is_symlink():
        status("BLOCK", "SQLite archive absent or symbolic link")
        return 2
    st = DB.stat()
    status("Archive bytes", st.st_size)
    status("Archive modification age (seconds)", age_seconds(st))
    wal = Path(str(DB) + "-wal")
    status("WAL", "present" if wal.is_file() else "absent")
    if wal.is_file():
        status("WAL bytes", wal.stat().st_size)
        status("WAL modification age (seconds)", age_seconds(wal.stat()))
    try:
        scope_path = Path(os.environ.get("CONTABO_DISCORD_SCOPE_PATH", str(HERE / "scope.py")))
        spec = importlib.util.spec_from_file_location("discord_scope", scope_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Scope helper not found")
        scope = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scope)

        uri = "file:" + quote(str(DB), safe="/") + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"channels", "messages", "scans"} <= tables:
                status("BLOCK", "Archive schema missing one of channels/messages/scans")
                return 2

            rows = scope.selected_rows(db)
            status("Scoped channels", len(rows))
            summary = {}
            for r in rows:
                label = category(r["kind"])
                item = summary.setdefault(label, [0, 0, 0, 0])
                item[0] += 1
                item[1] += int(r["complete"] == 1)
                item[2] += int(r["complete"] == 1 and r["refresh_active"] == 0 and
                               r["refreshed_at"] is not None and r["error"] is None)
                item[3] += int(bool(r["error"]))
            for label, (n, backfilled, refreshed, errors) in sorted(summary.items()):
                status(label, f"channels={n}, backfilled={backfilled}, refreshed={refreshed}, errors={errors}")

            total = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            status("All stored message rows (all scopes)", total)
            ids = [str(r["id"]) for r in rows]
            scoped_messages = 0
            for start in range(0, len(ids), 400):
                batch = ids[start:start + 400]
                q = ",".join("?" for _ in batch)
                scoped_messages += db.execute(
                    f"SELECT COUNT(*) FROM messages WHERE channel_id IN ({q})", batch
                ).fetchone()[0]
            status("Selected-scope stored message rows", scoped_messages)

            parents = scope.selected_parent_ids(db)
            selected_scans = [r for r in db.execute("SELECT scope,ok,error FROM scans")
                              if scope.selected_scan(r["scope"], parents)]
            failed = [r for r in selected_scans if r["ok"] != 1]
            status("Scope discovery scans", len(selected_scans))
            status("Scope discovery failures", len(failed))
            for r in failed[:10]:
                code = re.search(r"\b(?:HTTP )?([45]\d\d)\b", str(r["error"] or ""))
                status("Failed scan type", category_scan(r["scope"]) +
                       (f" (HTTP {code.group(1)})" if code else " (code unavailable)"))
            expected = {"dms", "guilds", f"guild:{scope.TARGET_GUILD}"}
            successful = {r["scope"] for r in selected_scans if r["ok"] == 1}
            status("Required discovery classes complete", len(expected & successful))
            status("Required discovery classes total", len(expected))
            if not rows or failed or any(r["complete"] != 1 or
                 r["refresh_active"] != 0 or r["refreshed_at"] is None or
                 r["error"] is not None for r in rows) or not expected <= successful:
                status("ARCHIVE", "INCOMPLETE: do not import/cut over as complete")
            else:
                status("ARCHIVE", "Known selected channels two-pass complete; discovery coverage still limited")
            if args.deep:
                deep_audit(db, ids)
            status("Matrix native historical import", "NOT VERIFIED")
            status("Media attachment parity", "NOT VERIFIED")
            return 0
    except (OSError, sqlite3.Error, ValueError, KeyError, RuntimeError) as exc:
        status("BLOCK", "Archive read failed: " + type(exc).__name__ +
               " (details intentionally hidden)")
        return 2

if __name__ == "__main__":
    sys.exit(main())
