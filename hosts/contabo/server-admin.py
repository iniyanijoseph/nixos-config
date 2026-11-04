#!/usr/bin/env python3
"""Private Contabo invitations, message metadata graphs, and bridge checks."""
import argparse
import csv
import fcntl
from datetime import datetime, timedelta, timezone
import getpass
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import yaml

OWNER = '@me:iniyanjoseph.com'
SERVER = 'http://127.0.0.1:8008'
PRIVATE = Path('/var/lib/contabo-admin')
BRIDGES = {
    'discord': ('mautrix-discord-native', 29322),
    'whatsapp': ('mautrix-whatsapp', 29318),
    'gmessages': ('mautrix-gmessages', 29320),
    'slack': ('mautrix-slack', 29321),
    'matrimail': ('matrimail', 29319),
}


def atomic_private(path, text, mode=0o600, gid=None):
    path = Path(path)
    if path.parent.is_symlink():
        raise RuntimeError('Symlinked private directory refused')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.prepare-', delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), mode)
            if gid is not None:
                os.fchown(stream.fileno(), -1, gid)
            stream.write(text)
            stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_private(path):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o007:
            raise RuntimeError('Unsafe private file permissions')
        return stream.read()


def api(path, token=None, body=None, method=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(SERVER + path, headers=headers,
                      data=None if body is None else json.dumps(body).encode(),
                      method=method or ('GET' if body is None else 'POST'))
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def admin_token(directory=PRIVATE):
    path = directory / 'admin-session.json'
    if path.exists():
        data = json.loads(read_private(path))
        token, user = data['access_token'], data['user_id']
    else:
        user = input(f'Matrix administrator [{OWNER}]: ').strip() or OWNER
        password = getpass.getpass('Matrix password (hidden): ')
        result = api('/_matrix/client/v3/login', body={
            'type': 'm.login.password', 'identifier': {'type': 'm.id.user', 'user': user},
            'password': password, 'initial_device_display_name': 'Private Contabo administration'})
        token, user = result['access_token'], result['user_id']
        del password
    verified = api('/_synapse/admin/v1/users/' + quote(user, safe='') + '/admin', token)
    if verified.get('admin') is not True:
        raise RuntimeError('This Matrix account is not a server administrator')
    if not path.exists():
        atomic_private(path, json.dumps({'access_token': token, 'user_id': user}))
    return token


def invite(hours=72, token=None, now=None):
    if not 1 <= hours <= 720:
        raise ValueError('Invitation lifetime must be 1–720 hours')
    token = token or admin_token()
    now = time.time() if now is None else now
    invitation = secrets.token_urlsafe(32)
    expiry = int((now + hours * 3600) * 1000)
    result = api('/_synapse/admin/v1/registration_tokens/new', token, {
        'token': invitation, 'uses_allowed': 1, 'expiry_time': expiry})
    if result.get('token') != invitation or result.get('uses_allowed') != 1 or result.get('expiry_time') != expiry:
        raise RuntimeError('Synapse did not confirm a single-use expiring invitation')
    return 'https://matrix.iniyanjoseph.com/invite/#token=' + quote(invitation, safe=''), expiry


def sql_string(value):
    return "'" + value.replace("'", "''") + "'"


def postgres(sql):
    script = "BEGIN READ ONLY;\nSET LOCAL statement_timeout='30s';\n" + sql + '\nCOMMIT;\n'
    result = subprocess.run(['runuser', '-u', 'postgres', '--', 'psql', '-X', '-q',
                             '-v', 'ON_ERROR_STOP=1', '-d', 'matrix-synapse'],
                            input=script, text=True, capture_output=True, check=True, timeout=40)
    return list(csv.DictReader(io.StringIO(result.stdout)))


def stats_query(start_ms, end_ms, zone, room=None):
    ZoneInfo(zone)
    where_room = '' if room is None else ' AND e.room_id=' + sql_string(room)
    # Counts metadata only: no body, subject, attachment URL or decrypted content
    # leaves PostgreSQL. Edits are excluded when the relation is unencrypted.
    return f'''COPY (
      SELECT e.room_id, coalesce(s.name,e.room_id) AS room_name,
        to_char(to_timestamp(e.origin_server_ts/1000.0) AT TIME ZONE {sql_string(zone)},'YYYY-MM-DD') AS day,
        e.sender, count(*) AS messages
      FROM events e LEFT JOIN room_stats_state s ON s.room_id=e.room_id
      LEFT JOIN event_json j ON j.event_id=e.event_id
      WHERE e.type IN ('m.room.message','m.room.encrypted') AND NOT e.outlier
        AND e.origin_server_ts >= {int(start_ms)} AND e.origin_server_ts < {int(end_ms)}
        AND coalesce(j.json::jsonb->'content'->'m.relates_to'->>'rel_type','') != 'm.replace'
        {where_room}
      GROUP BY e.room_id,s.name,day,e.sender ORDER BY e.room_id,day,e.sender
    ) TO STDOUT WITH CSV HEADER;'''


def aggregate(rows, days=90, zone='America/New_York', now=None):
    if not 7 <= days <= 366:
        raise ValueError('Choose 7–366 days')
    tz = ZoneInfo(zone)
    today = (now or datetime.now(timezone.utc)).astimezone(tz).date()
    first = today - timedelta(days=days - 1)
    warmup = first - timedelta(days=6)
    dates = [(warmup + timedelta(days=i)).isoformat() for i in range(days + 6)]
    rooms = {}
    for row in rows:
        room = rooms.setdefault(row['room_id'], {'id': row['room_id'], 'name': row['room_name'], 'daily': {}, 'people': {}})
        count = int(row['messages'])
        if count < 0:
            raise ValueError('Negative message count')
        day = row['day']
        room['daily'][day] = room['daily'].get(day, 0) + count
        if first.isoformat() <= day <= today.isoformat():
            room['people'][row['sender']] = room['people'].get(row['sender'], 0) + count
    for room in rooms.values():
        counts = [room['daily'].get(day, 0) for day in dates]
        room['days'] = [{'date': dates[i], 'count': counts[i], 'average': sum(counts[i-6:i+1]) / 7} for i in range(6, len(dates))]
        room['total'] = sum(person for person in room['people'].values())
        room['people'] = [{'id': person, 'count': count, 'ratio': count / room['total'] if room['total'] else 0}
                          for person, count in sorted(room['people'].items(), key=lambda pair: (-pair[1], pair[0]))]
        del room['daily']
    return {'timezone': zone, 'generated': datetime.now(timezone.utc).isoformat(),
            'rooms': sorted(rooms.values(), key=lambda room: (-room['total'], room['name'])),
            'definition': 'Matrix message/encrypted events, by original event date. Attachment parts count separately. Encrypted edits/notices cannot be distinguished without decryption. Ratios are per Matrix sender ID; identities are not inferred.'}


def make_stats(days=90, room=None, zone='America/New_York', now=None):
    if not 7 <= days <= 366:
        raise ValueError('Choose 7–366 days')
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(zone)).date()
    start = datetime.combine(today - timedelta(days=days + 5), datetime.min.time(), ZoneInfo(zone))
    end = datetime.combine(today + timedelta(days=1), datetime.min.time(), ZoneInfo(zone))
    rows = postgres(stats_query(int(start.timestamp()*1000), int(end.timestamp()*1000), zone, room))
    return aggregate(rows, days, zone, now)


def render_stats(data, template):
    # A room name such as </script> must remain data, never executable markup.
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return template.replace('/*CONTABO_DATA*/null', payload)


def sqlite_mappings(path, limit=200):
    connection = sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True, timeout=2)
    try:
        columns = {row[1] for row in connection.execute('PRAGMA table_info(message)')}
        if 'mxid' not in columns:
            return []
        return [row[0] for row in connection.execute("SELECT mxid FROM message WHERE mxid LIKE '$%' ORDER BY rowid DESC LIMIT ?", (limit,))]
    finally:
        connection.close()


def mapping_proof(events, now=None, minutes=30):
    cutoff = int(((time.time() if now is None else now) - minutes*60)*1000)
    inbound = outbound = 0
    for row in events:
        if int(row['timestamp']) < cutoff:
            continue
        if row['sender'] == OWNER:
            outbound += 1
        else:
            inbound += 1
    return {'recent_inbound_mappings': inbound, 'recent_outbound_mappings': outbound,
            'recent_both_directions': inbound > 0 and outbound > 0}


def bridge_provisioning_secret(network, value, env_path=Path('/var/lib/secrets/mautrix-whatsapp.env')):
    # The declarative WhatsApp config intentionally references a protected env
    # variable rather than storing the credential in its YAML. Resolve only
    # that exact placeholder for the read-only loopback health probe.
    if network != 'whatsapp' or value != '$WHATSAPP_PROVISIONING_SECRET':
        return value
    entries = [line.split('=', 1)[1].strip() for line in read_private(env_path).splitlines()
               if line.startswith('WHATSAPP_PROVISIONING_SECRET=')]
    if len(entries) != 1 or len(entries[0]) < 32:
        raise RuntimeError('WhatsApp provisioning credential missing or invalid')
    return entries[0]


def bridge_check(network, room=None, minutes=30):
    unit, port = BRIDGES[network]
    result = {'network': network, 'service_active': subprocess.run(
        ['systemctl', 'is-active', '--quiet', unit], stdout=subprocess.DEVNULL).returncode == 0,
        'connected': None, 'delivery': 'UNVERIFIED'}
    config = yaml.safe_load(read_private(Path('/var/lib') / unit / 'config.yaml'))
    if config.get('appservice', {}).get('hostname') != '127.0.0.1':
        raise RuntimeError('Expected loopback-only bridge listener')
    provisioning = config.get('bridge', {}).get('provisioning', {}) if network == 'discord' else config.get('provisioning', {})
    secret = bridge_provisioning_secret(network, provisioning.get('shared_secret'))
    if not isinstance(secret, str) or secret in ('disable', 'generate', '') or secret.startswith('$'):
        result['api'] = 'not configured'
    else:
        endpoint = '/_matrix/provision/v1/ping' if network == 'discord' else '/_matrix/provision/v3/whoami'
        request = Request(f'http://127.0.0.1:{port}' + endpoint + '?user_id=' + quote(OWNER, safe=''),
                          headers={'Authorization': 'Bearer ' + secret})
        with urlopen(request, timeout=15) as response:
            state = json.load(response)
        if network == 'discord':
            state = state.get('discord', state.get('Discord', {}))
            result['connected'] = bool(state.get('logged_in') and state.get('connected'))
        else:
            logins = state.get('logins', [])
            states = [login.get('state', {}).get('state_event', login.get('state_event', 'UNKNOWN')) for login in logins]
            result['login_states'] = states
            result['connected'] = bool(states) and all(value == 'CONNECTED' for value in states)
        result['api'] = 'responded'
    database = config.get('database', config.get('appservice', {}).get('database', {}))
    uri = database.get('uri', '')
    if uri.startswith('file:/var/lib/' + unit + '/'):
        path = Path(uri[5:].split('?', 1)[0])
        ids = sqlite_mappings(path)
        if ids:
            where_room = '' if room is None else ' AND room_id=' + sql_string(room)
            events = postgres('COPY (SELECT event_id,sender,origin_server_ts AS timestamp FROM events WHERE event_id IN (' +
                              ','.join(sql_string(event) for event in ids) + ')' + where_room + ') TO STDOUT WITH CSV HEADER;')
            result.update(mapping_proof(events, minutes=minutes))
            result['delivery'] = 'RECENT_MAPPING_EVIDENCE' if result['recent_both_directions'] else 'NEEDS_CLIENT_SEND_RECEIVE_TEST'
    return result


def ensure_whatsapp_secret(path=Path('/var/lib/secrets/mautrix-whatsapp.env')):
    content = read_private(path)
    for line in content.splitlines():
        if line.startswith('WHATSAPP_PROVISIONING_SECRET='):
            if len(line.split('=', 1)[1].strip()) < 32:
                raise RuntimeError('Unexpected WhatsApp provisioning secret; preserved')
            return False
    info = path.stat()
    atomic_private(path, content.rstrip() + '\nWHATSAPP_PROVISIONING_SECRET=' + secrets.token_hex(48) + '\n', mode=info.st_mode & 0o777, gid=info.st_gid)
    return True



def mail_consolidation_status(home=Path('/var/lib/matrimail')):
    """Read-only, sanitized progress audit of native Matrimail room mappings."""
    home = Path(home)
    config = yaml.safe_load(read_private(home / 'config.yaml'))
    enabled = config.get('network', {}).get('contact_rooms') is True
    uri = config.get('database', {}).get('uri', '')
    if not isinstance(uri, str) or not uri.startswith('file:'):
        raise RuntimeError('Matrimail audit requires a file-backed SQLite database')
    db_path = Path(uri.split('?', 1)[0][5:])
    if not db_path.is_absolute():
        db_path = home / db_path
    if not db_path.resolve().is_relative_to(home.resolve()):
        raise RuntimeError('Matrimail database is outside the expected private directory')
    if not db_path.is_file():
        raise RuntimeError('Matrimail database file does not exist')
    with sqlite3.connect('file:' + str(db_path) + '?mode=ro', uri=True, timeout=5) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'portal', 'message'}.issubset(tables):
            raise RuntimeError('Matrimail native portal/message tables are missing')
        def count(query):
            return int(db.execute(query).fetchone()[0])
        legacy_rooms = count("SELECT COUNT(*) FROM portal WHERE id LIKE 'thread:%' AND mxid IS NOT NULL AND mxid!=''")
        contact_rooms = count("SELECT COUNT(*) FROM portal WHERE id LIKE 'contact:%' AND mxid IS NOT NULL AND mxid!=''")
        old_parts = count("""SELECT COUNT(*) FROM message
            WHERE room_id LIKE 'thread:%' AND id LIKE 'email:%'
            AND mxid IS NOT NULL AND mxid!='' AND mxid NOT LIKE '~fake:%'""")
        new_parts = count("""SELECT COUNT(*) FROM message
            WHERE room_id LIKE 'contact:%' AND id LIKE 'contact-email:%'
            AND mxid IS NOT NULL AND mxid!='' AND mxid NOT LIKE '~fake:%'""")
        verified_parts = count("""SELECT COUNT(*) FROM message o
            WHERE o.room_id LIKE 'thread:%' AND o.id LIKE 'email:%'
              AND o.mxid IS NOT NULL AND o.mxid!='' AND o.mxid NOT LIKE '~fake:%'
              AND EXISTS (SELECT 1 FROM message n
                  WHERE n.bridge_id=o.bridge_id AND n.room_receiver=o.room_receiver
                    AND n.id='contact-email:' || substr(o.id,7)
                    AND n.part_id=o.part_id AND n.room_id LIKE 'contact:%'
                    AND n.mxid IS NOT NULL AND n.mxid!='' AND n.mxid NOT LIKE '~fake:%')""")
        retired = count("SELECT COUNT(*) FROM contabo_legacy_mail_retirement") if 'contabo_legacy_mail_retirement' in tables else 0
        accounts = count("SELECT COUNT(*) FROM email_accounts") if 'email_accounts' in tables else None
        logins = count("SELECT COUNT(*) FROM user_login") if 'user_login' in tables else None
        cursors = len(list((home / 'contabo-backfill-contacts-v2').glob('*.json')))
    if not enabled:
        assessment = 'Contact-room routing is disabled in the live bridge config'
    elif logins == 0:
        assessment = 'No saved bridge login: IMAP replay cannot start'
    elif contact_rooms == 0 or new_parts == 0:
        assessment = 'No populated contact rooms exist; historical consolidation is not yet verified'
    elif legacy_rooms == 0:
        assessment = 'No native legacy portals detected; this does not prove all old Matrix rooms were consolidated'
    elif verified_parts < old_parts:
        assessment = 'Historical migration incomplete: legacy message parts lack verified contact-room mappings'
    elif retired < legacy_rooms:
        assessment = 'Mappings present but old rooms not all marked as archived'
    else:
        assessment = 'Native mappings and old-room labels appear complete; verify in Matrix client'
    return {
        'contact_routing_enabled': enabled,
        'configured_accounts': accounts,
        'bridge_logins': logins,
        'legacy_rooms': legacy_rooms,
        'contact_rooms': contact_rooms,
        'legacy_message_parts': old_parts,
        'contact_message_parts': new_parts,
        'legacy_parts_with_contact_mappings': verified_parts,
        'archived_legacy_rooms': retired,
        'history_checkpoint_files': cursors,
        'assessment': assessment,
        'limitations': 'Read-only metadata audit. Does not prove IMAP source coverage, attachment parity, full Matrix event accessibility, or decrypted content.'
    }



def matrimail_legacy_cleanup_candidates(home=Path('/var/lib/matrimail')):
    """Only owner-scoped, verified retired *thread:* portals qualify.

    No contact room, non-Matrimail room, or unverified history can appear in
    this list. Do not rewrite the bridge database: native mapping evidence
    remains available after Synapse deletes the former Matrix room.
    """
    home = Path(home)
    report = mail_consolidation_status(home)
    if (not report['contact_routing_enabled'] or not report['contact_rooms']
            or report['legacy_message_parts'] == 0
            or report['legacy_parts_with_contact_mappings'] != report['legacy_message_parts']
            or report['archived_legacy_rooms'] < report['legacy_rooms']):
        raise RuntimeError('Legacy Matrimail cleanup blocked: verified replacement rooms and complete native mappings required')
    checkpoints = list((home / 'contabo-backfill-contacts-v2').glob('*.json'))
    if not checkpoints:
        raise RuntimeError('Legacy Matrimail cleanup blocked: no historical IMAP checkpoints')
    for path in checkpoints:
        checkpoint = json.loads(read_private(path))
        if checkpoint.get('after', -1) < checkpoint.get('waterline', 0):
            raise RuntimeError('Legacy Matrimail cleanup blocked: an IMAP history checkpoint has not completed')

    config = yaml.safe_load(read_private(home / 'config.yaml'))
    uri = config['database']['uri']
    if not isinstance(uri, str) or not uri.startswith('file:'):
        raise RuntimeError('Unexpected Matrimail SQLite URI')
    db_path = Path(uri.split('?', 1)[0][5:])
    if not db_path.is_absolute():
        db_path = home / db_path
    if not db_path.resolve().is_relative_to(home.resolve()):
        raise RuntimeError('Matrimail database is outside its private directory')
    with sqlite3.connect('file:' + str(db_path) + '?mode=ro', uri=True, timeout=5) as db:
        rows = db.execute("""
            SELECT p.mxid FROM portal p
            JOIN user_login u ON u.bridge_id=p.bridge_id AND u.id=p.receiver
            JOIN contabo_legacy_mail_retirement r ON r.bridge_id=p.bridge_id
                AND r.receiver=p.receiver AND r.portal_id=p.id
            WHERE u.user_mxid=? AND p.id LIKE 'thread:%'
                AND p.mxid IS NOT NULL AND p.mxid!=''
            ORDER BY p.mxid
        """, (OWNER,)).fetchall()
    room_ids = [row[0] for row in rows]
    if len(room_ids) != len(set(room_ids)):
        raise RuntimeError('Duplicate native Matrimail room identifiers; refusing cleanup')
    for room_id in room_ids:
        if not isinstance(room_id, str) or not room_id.startswith('!') or not room_id.endswith(':iniyanjoseph.com'):
            raise RuntimeError('Unexpected/nonlocal Matrimail room; refusing cleanup')
    return room_ids


def prune_matrimail_legacy_rooms(home=Path('/var/lib/matrimail'),
                                directory=PRIVATE, apply=False, limit=25,
                                backup_path=Path('/var/lib/migration-queue/finish-setup/backup.json')):
    """Preview by default. Delete only archived native thread rooms after replay."""
    if limit < 1 or limit > 100:
        raise ValueError('Choose 1–100 rooms per run')
    candidates = matrimail_legacy_cleanup_candidates(home)
    ledger_path = directory / 'matrimail-legacy-room-deletions.json'
    ledger = json.loads(read_private(ledger_path)) if ledger_path.exists() else {}
    pending = [room for room in candidates if room not in ledger]
    if not apply:
        return {'mode': 'preview', 'verified_legacy_rooms': len(candidates),
                'previously_submitted': len(candidates)-len(pending),
                'eligible_not_submitted': len(pending),
                'next_batch': pending[:limit],
                'warning': 'Deleting a room permanently purges its Matrix events; it does not alter source IMAP mail or the native bridge mapping database.'}
    if not backup_path.is_file() or time.time() - backup_path.stat().st_mtime > 24*3600:
        raise RuntimeError('A fresh, verified offsite snapshot from the setup runner is required before deleting Matrix rooms')
    token = admin_token(directory)
    submitted = []
    for room_id in pending[:limit]:
        result = api('/_synapse/admin/v2/rooms/' + quote(room_id, safe=''),
                     token, body={'block': True, 'purge': True}, method='DELETE')
        delete_id = result.get('delete_id')
        if not isinstance(delete_id, str) or not delete_id:
            raise RuntimeError('Synapse did not acknowledge a room deletion; subsequent rooms were left alone')
        ledger[room_id] = {'delete_id': delete_id, 'submitted_at': datetime.now(timezone.utc).isoformat()}
        atomic_private(ledger_path, json.dumps(ledger, indent=2))
        submitted.append(room_id)
    return {'mode': 'submitted', 'submitted': submitted,
            'remaining': len(pending)-len(submitted),
            'note': 'Synapse deletes asynchronously. These deletion requests were accepted; verify their status before describing the rooms as removed.'}



def matrimail_v3_duplicate_counts(db):
    """Sanitized, read-only v3 metrics. Old/v2-to-v3 copies are expected.

    A native source Message-ID assigned to multiple v3 portals is *not*
    expected and must block all automatic room purging. Do not disclose
    email addresses, Message-IDs, room IDs, or email bodies in this report.
    """
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'portal', 'message', 'user_login'}.issubset(tables):
        return {'v3_rooms': 0, 'v3_group_rooms': 0,
                'v3_conflicting_message_ids': 0, 'v3_shared_matrix_rooms': 0,
                'v3_native_parts': 0, 'v3_schema_available': False}
    portals = db.execute("""
        SELECT p.id,p.mxid FROM portal p JOIN user_login u
          ON u.bridge_id=p.bridge_id AND u.id=p.receiver
        WHERE u.user_mxid=? AND p.id LIKE 'contact-v3:%'
          AND p.mxid IS NOT NULL AND p.mxid!=''
    """, (OWNER,)).fetchall()
    groups = 0
    for portal_id, _ in portals:
        try:
            raw = portal_id.split(':', 1)[1]
            from base64 import urlsafe_b64decode
            contact = urlsafe_b64decode(
                raw + '=' * ((-len(raw)) % 4)).decode('utf-8')
            if ',' in contact:
                groups += 1
        except (ValueError, UnicodeError):
            # An invalid contact key is also suspicious; make it visible
            # as a potential group rather than exposing its raw contents.
            groups += 1
    conflicts = db.execute("""
        SELECT COUNT(*) FROM (
            SELECT m.bridge_id,m.room_receiver,m.id
            FROM message m JOIN user_login u
              ON u.bridge_id=m.bridge_id AND u.id=m.room_receiver
            WHERE u.user_mxid=? AND m.id LIKE 'contact-v3-email:%'
              AND m.room_id LIKE 'contact-v3:%'
              AND m.mxid IS NOT NULL AND m.mxid!=''
              AND m.mxid NOT LIKE '~fake:%'
            GROUP BY m.bridge_id,m.room_receiver,m.id
            HAVING COUNT(DISTINCT m.room_id)>1
        )
    """, (OWNER,)).fetchone()[0]
    shared_rooms = db.execute("""
        SELECT COUNT(*) FROM (
            SELECT p.bridge_id,p.receiver,p.mxid
            FROM portal p JOIN user_login u
              ON u.bridge_id=p.bridge_id AND u.id=p.receiver
            WHERE u.user_mxid=? AND p.id LIKE 'contact-v3:%'
              AND p.mxid IS NOT NULL AND p.mxid!=''
            GROUP BY p.bridge_id,p.receiver,p.mxid
            HAVING COUNT(DISTINCT p.id)>1
        )
    """, (OWNER,)).fetchone()[0]
    parts = db.execute("""
        SELECT COUNT(*) FROM message m JOIN user_login u
          ON u.bridge_id=m.bridge_id AND u.id=m.room_receiver
        WHERE u.user_mxid=? AND m.id LIKE 'contact-v3-email:%'
          AND m.room_id LIKE 'contact-v3:%'
          AND m.mxid IS NOT NULL AND m.mxid!=''
          AND m.mxid NOT LIKE '~fake:%'
    """, (OWNER,)).fetchone()[0]
    return {'v3_rooms': len(portals), 'v3_group_rooms': groups,
            'v3_conflicting_message_ids': conflicts,
            'v3_shared_matrix_rooms': shared_rooms,
            'v3_native_parts': parts, 'v3_schema_available': True}


def matrimail_v3_duplicate_audit(home=Path('/var/lib/matrimail')):
    home = Path(home)
    config = yaml.safe_load(read_private(home / 'config.yaml'))
    uri = config.get('database', {}).get('uri', '')
    if not isinstance(uri, str) or not uri.startswith('file:'):
        raise RuntimeError('Expected a private Matrimail SQLite database URI')
    path = Path(uri.split('?', 1)[0][5:])
    if not path.is_absolute():
        path = home / path
    if not path.resolve().is_relative_to(home.resolve()) or not path.is_file():
        raise RuntimeError('Matrimail database outside private directory')
    with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True, timeout=10) as db:
        counts = matrimail_v3_duplicate_counts(db)
    return {**counts, 'note': ('Old rooms alongside new v3 rooms are expected during replacement; '
                              'multiple v3 destinations for the same source Message-ID are not. '
                              'Native mappings cannot detect orphan Matrix events.')}


def matrimail_v3_rebuild_status(home=Path('/var/lib/matrimail')):
    """Read-only owner-scoped proof that source mail and old native parts
    have all been delivered into a *new* contact-v3: Matrix room.
    """
    home = Path(home)
    config = yaml.safe_load(read_private(home / 'config.yaml'))
    if config.get('network', {}).get('contact_rooms') is not True:
        raise RuntimeError('Matrimail v3 routing is not enabled')
    uri = config.get('database', {}).get('uri', '')
    if not isinstance(uri, str) or not uri.startswith('file:'):
        raise RuntimeError('Matrimail v3 requires a private SQLite database')
    path = Path(uri.split('?', 1)[0][5:])
    if not path.is_absolute():
        path = home / path
    if not path.resolve().is_relative_to(home.resolve()) or not path.is_file():
        raise RuntimeError('Matrimail v3 database is outside its private directory')
    base = home / 'contabo-backfill-contacts-v3'
    eligible = []
    blocked = []
    complete_accounts = 0
    old_parts_total = 0
    copied_parts_total = 0
    with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True, timeout=10) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        duplicates = matrimail_v3_duplicate_counts(db)
        required = {'portal', 'message', 'user_login', 'contabo_mail_v3_retirement'}
        if not required.issubset(tables):
            return {'ready': False, 'reason': 'v3 replay/retirement stage incomplete',
                    'eligible_rooms': 0, 'blocked_rooms': 0, 'complete_accounts': 0,
                    **duplicates}
        accounts = db.execute(
            'SELECT bridge_id,id FROM user_login WHERE user_mxid=?', (OWNER,)).fetchall()
        if not accounts:
            return {'ready': False, 'reason': 'No owner-scoped Matrimail account login',
                    'eligible_rooms': 0, 'blocked_rooms': 0, 'complete_accounts': 0}
        verified_accounts = set()
        for bridge_id, receiver in accounts:
            digest = hashlib.sha256(receiver.encode()).hexdigest()
            scope_file = base / ('scope-' + digest + '.json')
            try:
                scope = json.loads(read_private(scope_file))
                folders = scope['folders']
                files = scope['cursor_files']
                if (scope.get('version') != 3 or scope.get('account_hash') != digest
                        or scope.get('complete') is not True or not isinstance(folders, list)
                        or not folders or not isinstance(files, list)
                        or len(folders) != len(files) or len(set(folders)) != len(folders)
                        or len(set(files)) != len(files)
                        or (receiver.lower().endswith('@gmail.com')
                            and '[gmail]/all mail' not in {f.lower() for f in folders})):
                    raise ValueError('Incomplete v3 source-mail folder scope')
                for filename in files:
                    if not isinstance(filename, str) or len(filename) != 69 or not filename.endswith('.json'):
                        raise ValueError('Invalid frozen checkpoint file')
                    if any(char not in '0123456789abcdef' for char in filename[:-5]):
                        raise ValueError('Invalid checkpoint digest')
                    cursor = json.loads(read_private(base / filename))
                    if (cursor.get('version') != 1 or cursor.get('uid_validity', 0) < 1
                            or cursor.get('after', -1) < cursor.get('waterline', 0)):
                        raise ValueError('Incomplete or invalid frozen mailbox checkpoint')
                verified_accounts.add((bridge_id, receiver))
                complete_accounts += 1
            except (OSError, ValueError, KeyError, TypeError):
                pass
        portals = db.execute("""
            SELECT p.bridge_id,p.receiver,p.id,p.mxid
            FROM portal p JOIN user_login u
              ON u.bridge_id=p.bridge_id AND u.id=p.receiver
            WHERE u.user_mxid=? AND (p.id LIKE 'thread:%' OR p.id LIKE 'contact:%')
              AND p.mxid IS NOT NULL AND p.mxid!=''
            ORDER BY p.mxid
        """, (OWNER,)).fetchall()
        for bridge_id, receiver, portal_id, mxid in portals:
            label = (bridge_id, receiver, portal_id, mxid)
            if (bridge_id, receiver) not in verified_accounts:
                blocked.append(label)
                continue
            # A room mapped by any other bridge portal is not solely owned
            # by this superseded email portal; refuse to delete it.
            shared = db.execute("""
                SELECT COUNT(*) FROM portal
                WHERE mxid=? AND NOT (bridge_id=? AND receiver=? AND id=?)
            """, (mxid, bridge_id, receiver, portal_id)).fetchone()[0]
            if shared:
                blocked.append(label)
                continue
            old = db.execute("""
                SELECT id,part_id FROM message
                WHERE bridge_id=? AND room_receiver=? AND room_id=?
                  AND mxid IS NOT NULL AND mxid!='' AND mxid NOT LIKE '~fake:%'
            """, (bridge_id, receiver, portal_id)).fetchall()
            if not old:
                blocked.append(label)
                continue
            old_parts_total += len(old)
            copied = 0
            supported = True
            for msg_id, part_id in old:
                if msg_id.startswith('email:'):
                    raw = msg_id[6:]
                elif msg_id.startswith('contact-email:'):
                    raw = msg_id[14:]
                else:
                    supported = False
                    break
                new_id = 'contact-v3-email:' + raw
                hits = db.execute("""
                    SELECT p.mxid FROM message n JOIN portal p
                      ON p.bridge_id=n.bridge_id AND p.receiver=n.room_receiver
                       AND p.id=n.room_id
                    WHERE n.bridge_id=? AND n.room_receiver=?
                      AND n.id=? AND n.part_id=?
                      AND n.room_id LIKE 'contact-v3:%'
                      AND n.mxid IS NOT NULL AND n.mxid!=''
                      AND n.mxid NOT LIKE '~fake:%'
                      AND p.mxid IS NOT NULL AND p.mxid!=''
                """, (bridge_id, receiver, new_id, part_id)).fetchall()
                if len(hits) != 1:
                    supported = False
                    break
                copied += 1
            copied_parts_total += copied
            retired = db.execute("""
                SELECT COUNT(*) FROM contabo_mail_v3_retirement
                WHERE bridge_id=? AND receiver=? AND portal_id=?
            """, (bridge_id, receiver, portal_id)).fetchone()[0]
            if (not supported or copied != len(old) or retired != 1
                    or not isinstance(mxid, str) or not mxid.startswith('!')
                    or not mxid.endswith(':iniyanjoseph.com')):
                blocked.append(label)
            else:
                eligible.append(mxid)
    unique = len(set(eligible)) == len(eligible) and not set(eligible).intersection(
        {x[3] for x in blocked})
    # An explicitly reset account has no old portals to retire: its complete
    # full-history source scope and populated v3 rooms are the final condition.
    # An outstanding reset marker prevents prematurely accepting a replay.
    fresh = (not portals and duplicates['v3_rooms'] > 0)
    if fresh:
        for bridge_id, receiver in accounts:
            digest = hashlib.sha256(receiver.encode()).hexdigest()
            if (base / ('reset-' + digest + '.pending')).exists():
                fresh = False
                break
    ready = bool((eligible or fresh) and not blocked and unique
                 and complete_accounts == len(accounts)
                 and duplicates['v3_conflicting_message_ids'] == 0
                 and duplicates['v3_shared_matrix_rooms'] == 0)
    return {'ready': ready, 'eligible_rooms': len(eligible) if unique else 0,
            'blocked_rooms': len(blocked), 'complete_accounts': complete_accounts,
            'owner_accounts': len(accounts), 'old_parts': old_parts_total,
            'verified_v3_parts': copied_parts_total, **duplicates,
            'assessment': ('All owner-scoped old rooms can be retired after offsite backup'
                           if ready else 'Waiting for complete v3 source replay and exact native mapping parity'),
            '_eligible_mxids': eligible if unique else []}


def matrimail_auto_rebuild_cleanup(home=Path('/var/lib/matrimail'),
                                  directory=PRIVATE,
                                  backup_path=Path('/var/lib/migration-queue/finish-setup/backup.json'),
                                  apply=False, limit=10):
    """Automatic, checkpointed Synapse deletion after side-by-side v3 parity.

    Do not request deletion while even one old owner-scoped room is unverified.
    In noninteractive mode an existing private administrator session is needed.
    """
    if not 1 <= limit <= 25:
        raise ValueError('Use a bounded batch of 1–25 old rooms')
    report = matrimail_v3_rebuild_status(home)
    candidates = report.pop('_eligible_mxids', [])
    if not report['ready']:
        return {'status': 'deferred', **report}
    if not candidates:
        return {'status': 'complete', 'eligible_rooms': 0,
                'reason': 'Fresh IMAP rebuild finished; no superseded rooms remain'}
    ledger_path = directory / 'matrimail-v3-deletion-ledger.json'
    ledger = json.loads(read_private(ledger_path)) if ledger_path.exists() else {}
    if not isinstance(ledger, dict):
        raise RuntimeError('Invalid v3 deletion ledger')
    pending = [room for room in candidates if room not in ledger]
    if not apply:
        return {'status': 'preview', **report, 'pending': len(pending)}
    if not backup_path.is_file() or time.time() - backup_path.stat().st_mtime > 24 * 3600:
        return {'status': 'deferred', 'reason': 'Fresh verified offsite backup required'}
    session = directory / 'admin-session.json'
    if not session.is_file():
        return {'status': 'deferred', 'reason': 'No cached Matrix administrator session; cannot purge unattended'}
    # Verify the cached token is still an active Synapse admin token before
    # calling the irreversible room-deletion endpoint.
    token = admin_token(directory)
    submitted = []
    for room_id in pending[:limit]:
        result = api('/_synapse/admin/v2/rooms/' + quote(room_id, safe=''),
                     token, body={'block': True, 'purge': True}, method='DELETE')
        deletion_id = result.get('delete_id')
        if not isinstance(deletion_id, str) or not deletion_id:
            raise RuntimeError('Synapse did not acknowledge room deletion; stopping')
        ledger[room_id] = {'delete_id': deletion_id,
                           'submitted_at': datetime.now(timezone.utc).isoformat()}
        atomic_private(ledger_path, json.dumps(ledger, indent=2))
        submitted.append(room_id)
    # The next invocation verifies previously accepted deletions. A submitted
    # request is not proof of completion; never release photo work just yet.
    incomplete = 0
    for room in candidates:
        if room not in ledger:
            incomplete += 1
            continue
        try:
            response = api('/_synapse/admin/v2/rooms/delete_status/' +
                           quote(ledger[room]['delete_id'], safe=''), token)
            if response.get('status') != 'complete':
                incomplete += 1
        except HTTPError as error:
            if error.code != 404:
                incomplete += 1
                continue
            # Synapse discards purge-status records after a restart or 24h.
            # A previously accepted deletion is complete only if its room is
            # also absent from the authoritative room-detail endpoint.
            try:
                api('/_synapse/admin/v1/rooms/' + quote(room, safe=''), token)
                incomplete += 1
            except HTTPError as lookup:
                if lookup.code != 404:
                    incomplete += 1
    return {'status': 'complete' if incomplete == 0 else 'in_progress',
            'submitted_now': len(submitted), 'remaining_or_unconfirmed': incomplete,
            'eligible_rooms': len(candidates)}



RESET_PORTAL_PREFIXES = ('thread:', 'contact:', 'contact-v3:')
RESET_MANIFEST = 'matrimail-owner-clean-reset.json'


def matrimail_reset_plan(home=Path('/var/lib/matrimail')):
    """List exclusively owned conversation portals. Never select bot DMs or
    other users' portals and never infer Matrix rooms by their human names.
    """
    home = Path(home)
    config = yaml.safe_load(read_private(home / 'config.yaml'))
    uri = config.get('database', {}).get('uri', '')
    if not isinstance(uri, str) or not uri.startswith('file:'):
        raise RuntimeError('Reset requires a private Matrimail SQLite database')
    db_path = Path(uri.split('?', 1)[0][5:])
    if not db_path.is_absolute():
        db_path = home / db_path
    if (not db_path.resolve().is_relative_to(home.resolve())
            or not db_path.is_file() or db_path.is_symlink()):
        raise RuntimeError('Matrimail database path is unsafe')
    with sqlite3.connect('file:' + str(db_path) + '?mode=ro', uri=True, timeout=10) as db:
        if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
            raise RuntimeError('Matrimail database integrity check failed')
        accounts = [dict(bridge_id=b, receiver=r) for b, r in db.execute(
            'SELECT bridge_id,id FROM user_login WHERE user_mxid=? ORDER BY id',
            (OWNER,)).fetchall()]
        if not accounts:
            raise RuntimeError('No owner Matrimail login; login state left unchanged')
        portals = [dict(bridge_id=b, receiver=r, portal_id=pid, mxid=mxid)
                   for b, r, pid, mxid in db.execute("""
                SELECT p.bridge_id,p.receiver,p.id,p.mxid FROM portal p
                JOIN user_login u ON u.bridge_id=p.bridge_id AND u.id=p.receiver
                WHERE u.user_mxid=?
                  AND (p.id LIKE 'thread:%' OR p.id LIKE 'contact:%'
                       OR p.id LIKE 'contact-v3:%')
                ORDER BY p.receiver,p.id
            """, (OWNER,)).fetchall()]
        rooms = []
        for p in portals:
            mxid = p['mxid']
            if not mxid:
                continue
            if not isinstance(mxid, str) or not mxid.startswith('!') or not mxid.endswith(':iniyanjoseph.com'):
                raise RuntimeError('Refusing unexpected or nonlocal Matrimail room identifier')
            # A room shared with another portal, login, or Matrix user is not
            # exclusively in the reset scope, regardless of its room name.
            shared = db.execute("""
                SELECT COUNT(*) FROM portal WHERE mxid=?
                AND NOT (bridge_id=? AND receiver=? AND id=?)
            """, (mxid, p['bridge_id'], p['receiver'], p['portal_id'])).fetchone()[0]
            if shared:
                raise RuntimeError('A Matrimail room is also referenced by another portal')
            if 'user_portal' in {x[0] for x in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}:
                other = db.execute("""
                    SELECT COUNT(*) FROM user_portal
                    WHERE bridge_id=? AND portal_id=? AND portal_receiver=? AND user_mxid!=?
                """, (p['bridge_id'], p['portal_id'], p['receiver'], OWNER)).fetchone()[0]
                if other:
                    raise RuntimeError('A Matrimail room has another owner mapping; it will not be purged')
            rooms.append(mxid)
        if len(rooms) != len(set(rooms)):
            raise RuntimeError('Duplicate Matrix room IDs in reset plan')
    return {'version': 1, 'owner': OWNER, 'db_path': str(db_path),
            'accounts': accounts, 'portals': portals, 'rooms': rooms}


def matrimail_reset_room_status(room, delete_id, token):
    try:
        status = api('/_synapse/admin/v2/rooms/delete_status/' +
                     quote(delete_id, safe=''), token)
        if status.get('status') == 'complete':
            return True
        if status.get('status') == 'failed':
            raise RuntimeError('Synapse reported a failed room deletion')
        return False
    except HTTPError as exc:
        if exc.code != 404:
            raise
        try:
            api('/_synapse/admin/v1/rooms/' + quote(room, safe=''), token)
        except HTTPError as details:
            if details.code == 404:
                return True
            raise
        # Status expired, but room still exists. Never assume it was purged.
        raise RuntimeError('Synapse forgot deletion status while the room still exists')


def matrimail_reset_clear_native(home, manifest):
    """Transactional, owner-scoped bridge reset, leaving login credentials,
    remote accounts, ghost identities, and other users' portals untouched.
    """
    path = Path(manifest['db_path'])
    with sqlite3.connect(str(path), timeout=30) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        db.execute('PRAGMA defer_foreign_keys=ON')
        for portal in manifest['portals']:
            cur = db.execute("""
                DELETE FROM portal WHERE bridge_id=? AND receiver=? AND id=?
            """, (portal['bridge_id'], portal['receiver'], portal['portal_id']))
            if cur.rowcount != 1:
                raise RuntimeError('Native Matrimail portal changed after the reset was planned')
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('contabo_email_chain_v3', 'contabo_email_message_v3',
                      'contabo_email_chain', 'contabo_email_message',
                      'contabo_mail_v3_retirement', 'contabo_legacy_mail_retirement'):
            if table not in tables:
                continue
            for account in manifest['accounts']:
                db.execute('DELETE FROM "' + table + '" WHERE bridge_id=? AND receiver=?',
                           (account['bridge_id'], account['receiver']))
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Reset would violate a bridge database foreign key')
        if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
            raise RuntimeError('Reset transaction failed database quick_check')
        db.commit()
    # v3 scope/cursors are per-login; never remove another user's checkpoints.
    base = Path(home) / 'contabo-backfill-contacts-v3'
    for account in manifest['accounts']:
        digest = hashlib.sha256(account['receiver'].encode()).hexdigest()
        scope_path = base / ('scope-' + digest + '.json')
        if scope_path.is_file():
            scope = json.loads(read_private(scope_path))
            for filename in scope.get('cursor_files', []):
                if (not isinstance(filename, str) or len(filename) != 69
                        or not filename.endswith('.json')
                        or any(ch not in '0123456789abcdef' for ch in filename[:-5])):
                    raise RuntimeError('Unexpected historical IMAP checkpoint filename')
                (base / filename).unlink(missing_ok=True)
            scope_path.unlink()
        atomic_private(base / ('reset-' + digest + '.pending'), 'full-history IMAP replay required\n')
    return len(manifest['portals'])


def matrimail_clean_reset(home=Path('/var/lib/matrimail'), directory=PRIVATE,
                         backup_receipt=Path('/var/lib/migration-queue/finish-setup/backup.json'),
                         apply=False, batch_size=10):
    """One-time, resumable removal of owner Matrimail conversation rooms.
    This intentionally does NOT require v3 parity with obsolete Matrix rooms:
    the user elected to discard them and reconstruct from source IMAP instead.
    """
    if not 1 <= batch_size <= 20:
        raise ValueError('Choose an API deletion concurrency of 1–20 rooms')
    manifest_path = Path(directory) / RESET_MANIFEST
    if not apply:
        if manifest_path.exists():
            existing = json.loads(read_private(manifest_path))
            done = sum(bool(item.get('complete')) for item in existing['deletions'].values())
            return {'status': existing.get('phase', 'deleting'),
                    'total_rooms': len(existing['rooms']),
                    'confirmed_deleted': done,
                    'native_portals': len(existing['portals']),
                    'accounts': len(existing['accounts'])}
        plan = matrimail_reset_plan(home)
        return {'status': 'preview', 'total_rooms': len(plan['rooms']),
                'native_portals': len(plan['portals']),
                'accounts': len(plan['accounts']),
                'warning': 'Permanent Matrix room deletion; source IMAP remains unchanged. '
                           'Bot management room, all login credentials, and other bridges are preserved.'}
    if os.uname().nodename.split('.')[0] != 'contabo':
        raise RuntimeError('Matrimail reset may only run on the Contabo server')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lockfd = os.open(directory / 'matrimail-clean-reset.lock',
                     os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if subprocess.run(['systemctl', 'is-active', '--quiet',
                           'contabo-finish-setup.service']).returncode == 0:
            raise RuntimeError('Finish-setup is currently active; do not race a NixOS switch')
        if subprocess.run(['systemctl', 'is-active', '--quiet',
                           'contabo-post-mail.service']).returncode == 0:
            raise RuntimeError('Post-mail worker is active; retry when it finishes')
        if not manifest_path.exists():
            if (not backup_receipt.is_file()
                    or time.time() - backup_receipt.stat().st_mtime > 24*3600):
                raise RuntimeError('A fresh verified R2 backup receipt is required before deleting Matrix rooms')
            if not (directory / 'admin-session.json').is_file():
                raise RuntimeError('Authenticate once using mail-admin-auth first')
        token = admin_token(directory)
        subprocess.run(['systemctl', 'stop', 'contabo-post-mail.timer'], check=True)
        subprocess.run(['systemctl', 'stop', 'matrimail.service'], check=True)
        if subprocess.run(['systemctl', 'is-active', '--quiet', 'matrimail.service']).returncode == 0:
            raise RuntimeError('Matrimail did not stop; refusing to delete rooms')
        if manifest_path.exists():
            plan = json.loads(read_private(manifest_path))
            if plan.get('owner') != OWNER or plan.get('version') != 1:
                raise RuntimeError('Unexpected reset ledger; refusing to resume')
        else:
            plan = matrimail_reset_plan(home)
            source_path = Path(plan['db_path'])
            available = shutil.disk_usage(directory).free
            if available < source_path.stat().st_size + 512*1024*1024:
                raise RuntimeError('Insufficient disk for a private pre-reset SQLite backup')
            backup_path = directory / ('matrimail-before-clean-reset-' +
                                       datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') +
                                       '.sqlite')
            if backup_path.exists():
                raise RuntimeError('Private pre-reset backup path already exists')
            with sqlite3.connect('file:' + str(source_path) + '?mode=ro', uri=True) as src:
                with sqlite3.connect(str(backup_path)) as dest:
                    src.backup(dest)
            backup_path.chmod(0o600)
            with sqlite3.connect('file:' + str(backup_path) + '?mode=ro', uri=True) as copy:
                if copy.execute('PRAGMA quick_check').fetchone() != ('ok',):
                    raise RuntimeError('Pre-reset SQLite backup verification failed')
            plan.update(phase='deleting', backup_file=str(backup_path),
                        deletions={}, created_at=datetime.now(timezone.utc).isoformat())
            atomic_private(manifest_path, json.dumps(plan))
        if plan['phase'] == 'complete':
            return {'status': 'complete', 'deleted_rooms': len(plan['rooms'])}
        # Bound parallel Synapse purge pressure. The ledger makes interruptions
        # safe: already accepted deletion IDs are never blindly re-submitted.
        while plan['phase'] == 'deleting':
            inflight = 0
            for room in plan['rooms']:
                row = plan['deletions'].get(room)
                if row and row.get('complete'):
                    continue
                if row:
                    if matrimail_reset_room_status(room, row['delete_id'], token):
                        row['complete'] = True
                        atomic_private(manifest_path, json.dumps(plan))
                    else:
                        inflight += 1
                    continue
                if inflight >= batch_size:
                    continue
                response = api('/_synapse/admin/v2/rooms/' + quote(room, safe=''),
                               token, body={'block': True, 'purge': True}, method='DELETE')
                delete_id = response.get('delete_id')
                if not isinstance(delete_id, str) or not delete_id:
                    raise RuntimeError('Synapse did not acknowledge room deletion')
                plan['deletions'][room] = {'delete_id': delete_id, 'complete': False}
                atomic_private(manifest_path, json.dumps(plan))
                inflight += 1
            if all(plan['deletions'].get(room, {}).get('complete') for room in plan['rooms']):
                plan['phase'] = 'native-reset'
                atomic_private(manifest_path, json.dumps(plan))
                break
            time.sleep(3)
        if plan['phase'] == 'native-reset':
            matrimail_reset_clear_native(home, plan)
            plan['phase'] = 'restarting'
            atomic_private(manifest_path, json.dumps(plan))
        if plan['phase'] == 'restarting':
            subprocess.run(['systemctl', 'start', 'matrimail.service'], check=True)
            subprocess.run(['systemctl', 'start', 'contabo-post-mail.timer'], check=True)
            plan['phase'] = 'complete'
            atomic_private(manifest_path, json.dumps(plan))
        return {'status': plan['phase'], 'deleted_rooms': len(plan['rooms']),
                'native_portals_removed': len(plan['portals']),
                'account_logins_preserved': len(plan['accounts']),
                'next': 'Matrimail will reconstruct only fresh v3 conversation rooms from IMAP'}
    finally:
        os.close(lockfd)


def storage_audit():
    for args in (['df', '-h', '/'], ['du', '-xhd1', '/var/lib'], ['du', '-xhd1', '/nix'], ['journalctl', '--disk-usage']):
        subprocess.run(args, check=True)
    print('Photo quarantine, source archives, databases and Matrix media are retained application data; cleanup does not remove them.')


def cleanup(apply=False):
    if not apply:
        print('Plan: rotate/vacuum journals to 300M; collect unreferenced Nix paths; remove obsolete Matrimail build caches only when the active service uses its Nix package. No application data or rollback generations are deleted.')
        return
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'contabo-finish-setup'], stdout=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError('Wait for the active setup run before cleaning build caches')
    subprocess.run(['journalctl', '--rotate', '--vacuum-size=300M'], check=True)
    subprocess.run(['nix-store', '--gc'], check=True)
    command = subprocess.check_output(['systemctl', 'show', '-p', 'ExecStart', '--value', 'matrimail'], text=True)
    if '/nix/store/' in command and '/var/lib/matrimail/bin/' not in command:
        for path in (Path('/home/wug/.cache/matrimail-source'), Path('/home/wug/.local/share/matrimail-build')):
            if path.is_dir() and path.resolve() == path.absolute():
                shutil.rmtree(path)
        binary = Path('/var/lib/matrimail/bin/matrimail')
        if binary.is_file() and not binary.is_symlink() and binary.stat().st_uid == 0:
            binary.unlink()
        old_root = Path('/var/lib/matrimail/olm-runtime')
        if old_root.is_symlink() and str(old_root.resolve()).startswith('/nix/store/'):
            old_root.unlink()
    print('Safe cleanup finished. Photo quarantine, archives, databases, media and rollback generations preserved.')


def serve(directory=PRIVATE, port=8766):
    access = read_private(directory / 'stats-access').strip()
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_GET(self):
            if self.path != '/' + access:
                self.send_error(404); return
            body = (directory / 'stats.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers(); self.wfile.write(body)
    http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    p = subs.add_parser('invite'); p.add_argument('--hours', type=int, default=72)
    p = subs.add_parser('revoke-invite'); p.add_argument('token')
    p = subs.add_parser('stats'); p.add_argument('--days', type=int, default=90); p.add_argument('--room'); p.add_argument('--timezone', default='America/New_York')
    p = subs.add_parser('bridges'); p.add_argument('--network', choices=BRIDGES); p.add_argument('--core', action='store_true'); p.add_argument('--record', action='store_true'); p.add_argument('--room'); p.add_argument('--minutes', type=int, default=30)
    subs.add_parser('whatsapp-secret'); subs.add_parser('storage'); subs.add_parser('mail-consolidation')
    p = subs.add_parser('mail-prune-legacy'); p.add_argument('--apply', action='store_true'); p.add_argument('--limit', type=int, default=25)
    p = subs.add_parser('mail-auto-rebuild'); p.add_argument('--apply', action='store_true'); p.add_argument('--limit', type=int, default=10)
    subs.add_parser('mail-duplicates')
    p = subs.add_parser('mail-reset'); p.add_argument('--apply', action='store_true'); p.add_argument('--batch-size', type=int, default=10)
    subs.add_parser('mail-admin-auth')
    subs.add_parser('configure-bridges')
    p = subs.add_parser('cleanup'); p.add_argument('--apply', action='store_true')
    p = subs.add_parser('serve'); p.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    if args.command != 'serve' and os.geteuid() != 0:
        raise RuntimeError('Run this server administration command with sudo')
    if args.command == 'invite':
        url, expires = invite(args.hours)
        print(url); print('Single use. Expires:', datetime.fromtimestamp(expires/1000, timezone.utc).isoformat())
    elif args.command == 'revoke-invite':
        api('/_synapse/admin/v1/registration_tokens/' + quote(args.token, safe=''), admin_token(), method='DELETE')
        print('Invitation revoked.')
    elif args.command == 'stats':
        data = make_stats(args.days, args.room, args.timezone)
        template = Path(os.environ.get('CONTABO_STATS_TEMPLATE', Path(__file__).with_name('server-stats.html'))).read_text()
        import grp
        gid = grp.getgrnam('contabo-stats').gr_gid
        PRIVATE.mkdir(mode=0o750, exist_ok=True); os.chown(PRIVATE, 0, gid); os.chmod(PRIVATE, 0o750)
        atomic_private(PRIVATE / 'stats.html', render_stats(data, template), 0o640, gid)
        if not (PRIVATE / 'stats-access').exists():
            atomic_private(PRIVATE / 'stats-access', secrets.token_urlsafe(32), 0o640, gid)
        subprocess.run(['systemctl', 'restart', 'contabo-stats'], check=True)
        print('On your laptop: ssh -N -L 127.0.0.1:8766:127.0.0.1:8766 wug@213.199.55.255')
        print('Then open: http://127.0.0.1:8766/' + read_private(PRIVATE / 'stats-access').strip())
    elif args.command == 'bridges':
        if not 1 <= args.minutes <= 10080:
            raise ValueError('Choose a verification window of 1–10080 minutes')
        results = []
        networks = [args.network] if args.network else ['discord', 'whatsapp', 'gmessages'] if args.core else BRIDGES
        for network in networks:
            try:
                results.append(bridge_check(network, args.room, args.minutes))
            except Exception as error:
                results.append({'network': network, 'check': 'FAILED', 'error_type': type(error).__name__})
        report = {'checked': datetime.now(timezone.utc).isoformat(), 'results': results,
                  'limit': 'Read-only service/session and native mapping checks. Successful recent mappings are evidence, not a guarantee of future delivery, media parity or encryption recovery.'}
        print(json.dumps(report, indent=2))
        if args.record:
            atomic_private(PRIVATE / 'bridge-health.json', json.dumps(report))
        if any(row.get('connected') is not True or not row.get('service_active') for row in results):
            return 2
    elif args.command == 'whatsapp-secret':
        ensure_whatsapp_secret()
    elif args.command == 'configure-bridges':
        import importlib.util
        spec = importlib.util.spec_from_file_location('commission', os.environ['CONTABO_COMMISSION_SCRIPT'])
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.configure_private_bridge_settings()
    elif args.command == 'storage':
        storage_audit()
    elif args.command == 'mail-consolidation':
        report = mail_consolidation_status()
        if Path('/var/lib/matrimail/contabo-backfill-contacts-v3').is_dir():
            v3 = matrimail_v3_rebuild_status()
            report['v3_rebuild'] = {k: v for k, v in v3.items() if not k.startswith('_')}
        print(json.dumps(report, indent=2))
    elif args.command == 'mail-prune-legacy':
        print(json.dumps(prune_matrimail_legacy_rooms(apply=args.apply, limit=args.limit), indent=2))
    elif args.command == 'mail-auto-rebuild':
        print(json.dumps(matrimail_auto_rebuild_cleanup(apply=args.apply, limit=args.limit), indent=2))
    elif args.command == 'mail-duplicates':
        print(json.dumps(matrimail_v3_duplicate_audit(), indent=2))
    elif args.command == 'mail-reset':
        print(json.dumps(matrimail_clean_reset(apply=args.apply, batch_size=args.batch_size), indent=2))
    elif args.command == 'mail-admin-auth':
        admin_token()
        print('Matrix administrator session authenticated and cached privately for safe, unattended Matrimail room cleanup.')
    elif args.command == 'cleanup':
        cleanup(args.apply)
    elif args.command == 'serve':
        serve(port=args.port)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except HTTPError as error:
        print(f'Administration request failed (HTTP {error.code}). Credentials and response bodies were not printed.', file=sys.stderr); sys.exit(1)
    except Exception as error:
        print(f'Administration failed: {error}', file=sys.stderr); sys.exit(1)
