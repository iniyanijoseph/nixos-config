#!/usr/bin/env python3
"""Private Matrix !status responder for Contabo migration.

Long-poll one private unencrypted room; answer only commands from the owner.
Never displays tokens, archive contents, or raw logs.
"""
import json
import os
import shutil
import subprocess
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
scopespec=importlib.util.spec_from_file_location("discord_scope",SYSPATH/"discord-archive"/"scope.py")
discord_scope=importlib.util.module_from_spec(scopespec)
scopespec.loader.exec_module(discord_scope)
spec=importlib.util.spec_from_file_location("matrix_alert",SYSPATH/"matrix-alert.py")
alerts=importlib.util.module_from_spec(spec)
spec.loader.exec_module(alerts)

def get_json(base, token, path, params=None):
    url=base.rstrip("/")+path+("?" + urlencode(params) if params else "")
    req=Request(url,headers={"Authorization":"Bearer "+token})
    with urlopen(req,timeout=45) as result:
        return json.load(result)

def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}

def _size(n):
    value=float(n)
    for unit in ("B", "KiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return "unknown"

def _age(when):
    if not when:
        return "unknown"
    try:
        dt=datetime.fromisoformat(str(when).replace("Z","+00:00"))
        seconds=max(0,int((datetime.now(timezone.utc)-dt).total_seconds()))
        if seconds < 3600:
            return f"{seconds//60}m ago"
        if seconds < 86400:
            return f"{seconds//3600}h {seconds%3600//60}m ago"
        return f"{seconds//86400}d ago"
    except (TypeError, ValueError):
        return "unknown"

def _unit_health():
    names=("matrix-synapse", "nginx", "mautrix-whatsapp",
           "discord-photos-queue", "matrix-command-listener")
    try:
        proc=subprocess.run(["systemctl","is-active",*names],
                            capture_output=True,text=True,timeout=5,check=False)
        result=proc.stdout.strip().splitlines()
        if len(result)!=len(names):
            return "unavailable"
        return ", ".join(f"{name}: {state}" for name,state in zip(names,result))
    except (OSError,subprocess.TimeoutExpired):
        return "unavailable"

def _backup_summary():
    # Report only confirmed completed snapshots, never infer from service activity.
    try:
        proc=subprocess.run(["restic-contabo","snapshots","--json"],
                            capture_output=True,text=True,timeout=12,check=False)
        if proc.returncode != 0:
            return "unavailable (snapshot query failed)"
        snapshots=json.loads(proc.stdout)
        if not snapshots:
            return "no snapshots found"
        newest=max(snapshots,key=lambda x:x.get("time",""))
        paths=set(newest.get("paths",[]))
        coverage=("photos + queue" if {"/var/lib/nextcloud","/var/lib/migration-queue"}<=paths
                  else "photos only" if "/var/lib/nextcloud" in paths
                  else "Nextcloud not in latest snapshot")
        return f"{_age(newest.get('time'))} [{str(newest.get('short_id') or newest.get('id',''))[:8]}]; {coverage}"
    except (OSError,ValueError,TypeError,subprocess.TimeoutExpired):
        return "unavailable"

def status_text():
    """Read-only operational summary. No hashing, mutation or network requests."""
    lines=["CONTABO | Migration and health",
           f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"]
    manifest=_read_json(STATE/"photos-manifest.json")
    expected=len(manifest.get("files",{}))
    stages=[
        ("Photo reconciliation","photos-reconciled.json"),
        ("Google Takeout metadata","photos-migrated.json"),
        ("Memories indexing","photos-indexed.json"),
        ("Quarantine cleanup","photos-quarantine-cleaned.json"),
        ("Mail/bridge preflight","services-staged.json"),
    ]
    flags={name:(STATE/file).exists() for name,file in stages}
    lines.extend(["", "PHOTOS", f"Takeout manifest: {expected or 'unknown'} files",
                  "Reconciliation: "+("verified, complete" if flags["Photo reconciliation"] else "pending")])
    repair=_read_json(STATE/"photos-reconciled.json")
    if repair:
        outcome=repair.get("result",{})
        lines.append(f"Restored: {outcome.get('restored','?')}; quarantined: {outcome.get('quarantined','?')}")
        lines.append("Verification: "+str(repair.get("verified","checkpoint present"))[:100])
        lines.append("Reconciled: "+_age(repair.get("finished")))
    if not flags["Photo reconciliation"]:
        observed=_read_json(STATE/"photos-upload-observation.json")
        if "first_seen" in observed:
            try:
                elapsed=max(0,int(time.time()-float(observed["first_seen"])))
                lines.append(f"Upload quiet period: {min(600,elapsed)}/600s")
            except (ValueError, TypeError):
                pass
    for name,_ in stages[1:]:
        checkpoint=_read_json(STATE/dict(stages)[name])
        detail="done" if flags[name] else "pending"
        if flags[name]:
            detail+=f" ({_age(checkpoint.get('finished') or checkpoint.get('checked'))})"
        lines.append(f"{name}: {detail}")
    quarantine=STATE/"photos-duplicate-quarantine"
    try:
        if quarantine.is_dir() and not quarantine.is_symlink():
            # Do not traverse 7k files on each !status.
            lines.append("Quarantine: retained (size not scanned); cleanup requires post-index backup")
        elif flags["Quarantine cleanup"]:
            lines.append("Quarantine: removed after verified backup")
    except OSError:
        pass
    lines.extend(["",f"DISCORD | DMs + guild {discord_scope.TARGET_GUILD}"])
    try:
        uri="file:"+str(DB)+"?mode=ro"
        conn=sqlite3.connect(uri,uri=True,timeout=5)
        conn.row_factory=sqlite3.Row
        try:
            rows=discord_scope.selected_rows(conn)
            total=len(rows)
            done=sum(r["complete"]==1 for r in rows)
            fresh=sum(r["complete"]==1 and r["refresh_active"]==0 and
                      r["refreshed_at"] is not None and r["error"] is None for r in rows)
            errors=[r for r in rows if r["error"]]
            types={}
            for row in rows:
                kind=row["kind"]
                label=("DMs" if kind=="dms" else
                       "Target guild channels" if kind==f"guild:{discord_scope.TARGET_GUILD}" else
                       "Threads")
                types.setdefault(label,[0,0,0])
                types[label][0]+=1
                types[label][1]+=int(row["complete"]==1)
                types[label][2]+=int(row["refreshed_at"] is not None and row["refresh_active"]==0)
            # A single SQL aggregate over selected IDs avoids thousands of queries.
            # Keep parameter lists under SQLite's variable limit.
            ids=[str(r["id"]) for r in rows]
            messages=0
            for start in range(0,len(ids),400):
                batch=ids[start:start+400]
                if batch:
                    placeholders=",".join("?" for _ in batch)
                    messages+=conn.execute(
                        f"SELECT COUNT(*) FROM messages WHERE channel_id IN ({placeholders})",
                        batch).fetchone()[0]
            parents=discord_scope.selected_parent_ids(conn)
            bad=[r for r in conn.execute("SELECT scope,error FROM scans WHERE ok!=1")
                 if discord_scope.selected_scan(r["scope"],parents)]
            known=[r for r in conn.execute("SELECT scope,ok FROM scans")
                   if discord_scope.selected_scan(r["scope"],parents)]
            percentage=(done+fresh)*100//(2*total) if total else 0
            lines.append(f"Saved messages (selected scope): {messages:,}")
            lines.append(f"Backfill: {done}/{total}; refresh: {fresh}/{total}")
            lines.append(f"Two-pass completion: ~{percentage}% of discovered work; not an ETA")
            for label,counts in sorted(types.items()):
                lines.append(f"  {label}: {counts[1]}/{counts[0]} backfilled, {counts[2]}/{counts[0]} refreshed")
            lines.append(f"Channel errors: {len(errors)}; discovery failures: {len(bad)}/{len(known)}")
            for r in bad[:3]:
                lines.append(f"  BLOCKER: {r['scope']} — {str(r['error'] or 'unspecified')[:110]}")
            for r in errors[:2]:
                lines.append(f"  CHANNEL ERROR: {r['id']} — {str(r['error'])[:95]}")
            if not total:
                lines.append("No selected channels discovered")
        finally:
            conn.close()
    except (sqlite3.Error,OSError,KeyError) as error:
        lines.append(f"Archive metrics unavailable: {type(error).__name__}")

    lines.extend(["", "SERVER HEALTH"])
    try:
        space=shutil.disk_usage("/")
        lines.append(f"Disk: {_size(space.used)} used, {_size(space.free)} free ({space.used*100//space.total}%)")
    except OSError:
        lines.append("Disk: unavailable")
    lines.append("Services: "+_unit_health())
    lines.append("Offsite Restic backup: "+_backup_summary())
    steps=[("Reconciliation",flags["Photo reconciliation"]),
           ("Metadata",flags["Google Takeout metadata"]),
           ("Index",flags["Memories indexing"]),
           ("Cleanup",flags["Quarantine cleanup"]),
           ("Preflight",flags["Mail/bridge preflight"])]
    next_step=next((name for name,ready in steps if not ready),"All photo stages complete")
    if not flags["Google Takeout metadata"]:
        next_step="Discord completion, then Google Takeout metadata"
    lines.extend(["","NEXT",next_step,
                  "Bridges: WhatsApp configured; Discord, SMS/RCS, Slack, Matrimail and mail staged/disabled.",
                  "Note: service status is systemd state, not a live chat delivery test."])
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
