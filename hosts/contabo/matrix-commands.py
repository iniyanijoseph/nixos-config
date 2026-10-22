#!/usr/bin/env python3
"""Private Matrix !status responder for Contabo migration.

Long-poll one private unencrypted room; answer only commands from the owner.
Never displays tokens, archive contents, or raw logs.
"""
import json
import os
from datetime import datetime, timezone
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

SECRET=Path("/var/lib/secrets/matrix-alerts.json")
STATE=Path("/var/lib/migration-queue")
DB=Path("/var/lib/discord-archive/archive.sqlite")
OWNER="@me:iniyanjoseph.com"
SYSPATH=Path(__file__).resolve().parent
sys.path.insert(0,str(SYSPATH))
import importlib.util
spec=importlib.util.spec_from_file_location("matrix_alert",SYSPATH/"matrix-alert.py")
alerts=importlib.util.module_from_spec(spec)
spec.loader.exec_module(alerts)

def get_json(base, token, path, params=None):
    url=base.rstrip("/")+path+("?" + urlencode(params) if params else "")
    req=Request(url,headers={"Authorization":"Bearer "+token})
    with urlopen(req,timeout=45) as result:
        return json.load(result)

def status_text():
    manifest=STATE/"photos-manifest.json"
    n=0
    if manifest.exists():
        n=len(json.loads(manifest.read_text())["files"])
    obs=STATE/"photos-upload-observation.json"
    if (STATE/"photos-reconciled.json").exists():
        photos="reconciled (100%)"
    elif obs.exists():
        try:
            observed=json.loads(obs.read_text())
            elapsed=max(0,int(time.time()-float(observed["first_seen"])))
            photos=f"SHA-256 verified; quiet-period {min(600,elapsed)}/600 seconds"
        except (OSError,ValueError,KeyError,TypeError):
            photos="SHA-256 verified; waiting for unchanged-file safety interval"
    else:
        photos="upload/verification incomplete"
    discord="archive not yet complete"
    try:
        uri="file:"+str(DB)+"?mode=ro"
        conn=sqlite3.connect(uri,uri=True,timeout=5)
        try:
            backfilled,refreshed,errors,total=conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN complete=1 THEN 1 ELSE 0 END),0), "
                "COALESCE(SUM(CASE WHEN complete=1 AND refresh_active=0 "
                "AND refreshed_at IS NOT NULL AND error IS NULL THEN 1 ELSE 0 END),0), "
                "COALESCE(SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END),0), "
                "COUNT(*) FROM channels").fetchone()
            messages=conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            failed,total_scans=0,0
            total_scans,failed=conn.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END),0) FROM scans").fetchone()
            pct=min(99,(backfilled+refreshed)*100//(2*total)) if total else 0
            discord=(f"{backfilled}/{total} backfilled; {refreshed}/{total} refreshed; "
                     f"{messages} messages saved; {errors} channel errors; "
                     f"{failed}/{total_scans} discovery checks failed; "
                     f"~{pct}% of currently known two-pass work (not an ETA)")
        finally:
            conn.close()
    except (sqlite3.Error,OSError):
        pass
    phases=[("Photo reconciliation","photos-reconciled.json"),
            ("Metadata migration","photos-migrated.json"),
            ("Memories indexing","photos-indexed.json"),
            ("Service preflight","services-staged.json")]
    lines=["Contabo migration status",f"Discord: {discord}",f"Google Photos: {photos}"]
    if n:
        lines.append(f"Takeout manifest: {n} entries")
    lines.extend(f"{name}: {'done' if (STATE/mark).exists() else 'pending'}" for name,mark in phases)
    p=STATE/"matrix-progress.json"
    try:
        progress=json.loads(p.read_text())
        if progress:
            lines.append("Last successfully notified percentages:")
            lines.extend(f"  {k}: {v}%" for k,v in sorted(progress.items()))
    except (OSError,ValueError):
        pass
    return "\n".join(lines)

def run():
    cfg=json.loads(SECRET.read_text())
    base=cfg["homeserver"]; room=cfg["room_id"]; token=cfg["access_token"]
    if not base.startswith("https://") or not room.startswith("!"):
        raise RuntimeError("Invalid private Matrix configuration")
    # First run intentionally skips existing room backlog to avoid answering
    # stale commands or self-replies.
    cursor=STATE/"matrix-command-sync.json"
    since=None
    if cursor.exists():
        since=json.loads(cursor.read_text()).get("next_batch")
    if not since:
        first=get_json(base,token,"/_matrix/client/v3/sync",{"timeout":0,"filter":json.dumps({"room":{"rooms":[room],"timeline":{"limit":0}}})})
        since=first["next_batch"]
        store_cursor(cursor,since)
    print("Matrix !status listener running",flush=True)
    while True:
        try:
            sync=get_json(base,token,"/_matrix/client/v3/sync",
                          {"since":since,"timeout":30000,
                           "filter":json.dumps({"room":{"rooms":[room],"timeline":{"limit":30,"types":["m.room.message"]}}})})
            for event in sync.get("rooms",{}).get("join",{}).get(room,{}).get("timeline",{}).get("events",[]):
                if event.get("type")!="m.room.message" or event.get("sender")!=OWNER:
                    continue
                body=event.get("content",{}).get("body","").strip().lower()
                if body in ("!status","!progress"):
                    alerts.send(status_text())
                elif body=="!help":
                    alerts.send("Commands: !status, !progress, !help")
            since=sync["next_batch"]
            store_cursor(cursor,since)
        except (OSError,ValueError,KeyError,HTTPError,URLError,sqlite3.Error) as err:
            print(f"Matrix command listener retrying after {type(err).__name__}: {err}",flush=True)
            time.sleep(10)

def store_cursor(path,value):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"next_batch":value})+"\n")
    os.chmod(tmp,0o600)
    tmp.replace(path)

if __name__=="__main__":
    run()
