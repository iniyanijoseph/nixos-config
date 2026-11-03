#!/usr/bin/env python3
"""Private Contabo invitations, message metadata graphs, and bridge checks."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import getpass
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


def bridge_check(network, room=None, minutes=30):
    unit, port = BRIDGES[network]
    result = {'network': network, 'service_active': subprocess.run(
        ['systemctl', 'is-active', '--quiet', unit], stdout=subprocess.DEVNULL).returncode == 0,
        'connected': None, 'delivery': 'UNVERIFIED'}
    config = yaml.safe_load(read_private(Path('/var/lib') / unit / 'config.yaml'))
    if config.get('appservice', {}).get('hostname') != '127.0.0.1':
        raise RuntimeError('Expected loopback-only bridge listener')
    provisioning = config.get('bridge', {}).get('provisioning', {}) if network == 'discord' else config.get('provisioning', {})
    secret = provisioning.get('shared_secret')
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
    subs.add_parser('whatsapp-secret'); subs.add_parser('storage')
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
