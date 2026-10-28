#!/usr/bin/env python3
"""Generate private bridge configurations and deploy a reversible NixOS generation.

No credentials are put in Git or the Nix store. Existing configs/registrations
are preserved. Authentication and message acceptance are reported separately.
"""
import json
import http.client
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import tempfile
import yaml
import socket
import base64
import urllib.request
import urllib.error
import sqlite3
import time
from urllib.parse import quote

REPO = Path('/etc/nixos')
HOST = REPO / 'hosts/contabo'
STATE = Path('/var/lib/migration-queue/integrations')


def run(args, capture=False):
    return subprocess.run([str(x) for x in args], check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def configure(template, name, port, directory):
    data = yaml.safe_load(template)
    data['homeserver'].update(address='http://127.0.0.1:8008', domain='iniyanjoseph.com')
    app = data['appservice']
    app.update(address=f'http://127.0.0.1:{port}', hostname='127.0.0.1', port=port)
    app.setdefault('bot', {})['username'] = name + 'bot'
    database = data.get('database', app.get('database'))
    if not isinstance(database, dict):
        raise RuntimeError('Unrecognized bridge database schema; no config written')
    database.update(type='sqlite3-fk-wal', uri=f'file:{directory}/bridge.db?_txlock=immediate')
    data['bridge']['permissions'] = {'*': 'block', '@me:iniyanjoseph.com': 'admin'}
    encryption = data.get('encryption', data['bridge'].get('encryption'))
    if not isinstance(encryption, dict):
        raise RuntimeError('Unrecognized encryption schema')
    encryption.update(allow=True, default=True, require=True)
    data.setdefault('provisioning', {})['shared_secret'] = 'disable'
    if isinstance(data.get('backfill'), dict):
        data['backfill'].update(enabled=True, max_initial_messages=10000)
    return yaml.safe_dump(data, sort_keys=False)


def provision(name, binary, port, directory):
    owner = pwd.getpwnam(name)
    directory.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chown(directory, owner.pw_uid, owner.pw_gid)
    config, registration = directory / 'config.yaml', directory / 'registration.yaml'
    if config.exists() != registration.exists():
        raise RuntimeError(f'{name}: incomplete existing provisioning; preserved for review')
    if config.exists():
        # Do not rotate encryption keys, tokens or registrations on rerun.
        if config.is_symlink() or registration.is_symlink():
            raise RuntimeError('Symlinked private configuration refused')
        return
    with tempfile.TemporaryDirectory(dir=directory, prefix='.prepare-') as temp:
        temp = Path(temp)
        os.chown(temp, owner.pw_uid, owner.pw_gid)
        cfg, reg = temp / 'config.yaml', temp / 'registration.yaml'
        run(['runuser', '-u', name, '--', binary, '-e', '-c', cfg])
        network = name.removeprefix('mautrix-')
        cfg.write_text(configure(cfg.read_text(), network, port, directory))
        os.chmod(cfg, 0o640)
        os.chown(cfg, owner.pw_uid, owner.pw_gid)
        run(['runuser', '-u', name, '--', binary, '-g', '-c', cfg, '-r', reg])
        generated = yaml.safe_load(reg.read_text())
        if generated.get('url') != f'http://127.0.0.1:{port}' or not all(
                generated.get(k) for k in ('id', 'as_token', 'hs_token', 'namespaces')):
            raise RuntimeError('Invalid generated appservice registration')
        for path in (cfg, reg):
            os.chmod(path, 0o640)
            os.chown(path, owner.pw_uid, owner.pw_gid)
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
        # Install registration first: interruption is detected on next run.
        reg.replace(registration)
        cfg.replace(config)


def private_json(path, data):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        os.chmod(temporary, 0o600)
        json.dump(data, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def discord_pilot_verified():
    try:
        result = json.loads((STATE/'discord-pilot-verified.json').read_text())
        return (isinstance(result, dict) and type(result.get('expected')) is int
                and result['expected'] > 0 and result.get('mapped') == result['expected']
                and isinstance(result.get('channel'), str) and result['channel'].isdecimal()
                and isinstance(result.get('receiver'), str) and result['receiver'].isdecimal())
    except (OSError, ValueError):
        return False


def build(enabled, mail=None, discord=None, pilot=None):
    def installed(unit):
        return subprocess.run(['systemctl','is-enabled','--quiet',unit],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if enabled is None:
        enabled = all(installed(unit) for unit in ('mautrix-gmessages','mautrix-slack','matrimail'))
    if mail is None:
        mail = installed('stalwart.service')
    if discord is None:
        discord = installed('mautrix-discord-native.service')
    if pilot is None:
        pilot = not discord_pilot_verified()
    expression = '''let f = builtins.getFlake "/etc/nixos/hosts/contabo";
      in (f.nixosConfigurations.contabo.extendModules { modules = [
        ({lib,...}: {contabo.integrations.enable = lib.mkForce %s;
          contabo.mail.enable = lib.mkForce %s;
          contabo.discordNative.enable = lib.mkForce %s;
          contabo.discordNative.pilot = lib.mkForce %s;})
      ]; }).config.system.build.toplevel''' % ('true' if enabled else 'false', 'true' if mail else 'false', 'true' if discord else 'false', 'true' if pilot else 'false')
    return run(['nix','build','--impure','--expr',expression,
                '--out-link',STATE/('connected' if enabled else 'staging'),
                '--print-out-paths'],capture=True).strip()


def discord_coverage(archive, mapping, channels, receiver=None):
    if not channels:
        return 0,0
    source=sqlite3.connect('file:'+str(archive)+'?mode=ro',uri=True)
    try:
        source.execute('ATTACH DATABASE ? AS bridge',('file:'+str(mapping)+'?mode=ro',))
        marks=','.join('?' for _ in channels)
        owner_clause=" AND b.dc_chan_receiver IN ('',?)" if receiver is not None else ''
        query=f'''SELECT count(*),sum(EXISTS(SELECT 1 FROM bridge.message b
          WHERE b.dc_chan_id=m.channel_id AND b.dcid=m.id {owner_clause}))
          FROM main.messages m WHERE m.channel_id IN ({marks})'''
        params=([receiver] if receiver is not None else [])+list(channels)
        expected,found=source.execute(query,params).fetchone()
        return expected,int(found or 0)
    finally:
        source.close()


def validate_discord_snapshot(path):
    source = sqlite3.connect('file:'+str(path)+'?mode=ro', uri=True)
    try:
        count, incomplete = source.execute("""SELECT count(*),sum(
          complete != 1 OR refresh_active != 0 OR refreshed_at IS NULL OR error IS NOT NULL)
          FROM channels WHERE kind IN ('dms','guild:804408079940583475')""").fetchone()
        if not count or incomplete:
            raise RuntimeError('Discord archive has unfinished channel collection/refresh; resume the collector before importing')
    finally:
        source.close()


def discord_api(base, token, endpoint, method='GET', payload=None):
    # These operations resume existing portals/mappings. Retrying a closed
    # connection must never rotate login credentials or recreate bridge state.
    retryable = ((method == 'GET' and endpoint == '/v1/ping') or
                 (method == 'POST' and endpoint in (
                     '/v1/contabo/archive', '/v1/guilds/804408079940583475')))
    attempts = 10 if retryable else 1
    query = '?user_id=' + quote('@me:iniyanjoseph.com', safe='')
    for attempt in range(attempts):
        request = urllib.request.Request(base + endpoint + query,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
            method=method)
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                return json.load(response)
        except urllib.error.HTTPError:
            # Authentication, source access and application errors need review,
            # not repeated requests that could hide a permanent failure.
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError,
                http.client.RemoteDisconnected, http.client.IncompleteRead) as error:
            if attempt == attempts - 1:
                raise RuntimeError(f'Discord API {method} {endpoint} failed after '
                    f'{attempts} attempts ({type(error).__name__}); '
                    'inspect journalctl -u mautrix-discord-native') from error
            print(f'WAITING: Discord API {method} {endpoint}: {type(error).__name__}; '
                  f'retrying {attempt + 2}/{attempts}', flush=True)
            time.sleep(min(attempt + 1, 5))


def wait_for_discord_connection(api):
    for attempt in range(30):
        ping = api('/v1/ping')
        connection = ping.get('Discord', ping.get('discord', {}))
        if connection.get('logged_in') and connection.get('connected'):
            return True
        if attempt < 29:
            time.sleep(1)
    return False


def commission_discord():
    prepare_identities()
    directory=Path('/var/lib/mautrix-discord-native')
    directory.mkdir(mode=0o750,exist_ok=True)
    owner=pwd.getpwnam('mautrix-discord-native')
    os.chown(directory,owner.pw_uid,owner.pw_gid)
    snapshot=directory/'archive.sqlite'
    if not snapshot.exists():
        original=Path('/var/lib/discord-archive/archive.sqlite')
        if shutil.disk_usage(directory).free < original.stat().st_size+5*1024**3:
            raise RuntimeError('Insufficient space for a consistent migration snapshot')
        source=sqlite3.connect('file:'+str(original)+'?mode=ro',uri=True)
        temp=directory/'archive.preparing'
        temp.unlink(missing_ok=True)
        destination=sqlite3.connect(temp)
        try:
            source.backup(destination,pages=1024)
            destination.execute('CREATE INDEX IF NOT EXISTS contabo_message_order ON messages(channel_id,length(id),id)')
            destination.commit()
            if destination.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:
                raise RuntimeError('Discord archive snapshot failed integrity check')
        finally:
            source.close();destination.close()
        validate_discord_snapshot(temp)
        os.chmod(temp,0o440);os.chown(temp,0,owner.pw_gid)
        temp.replace(snapshot)
    validate_discord_snapshot(snapshot)
    config=directory/'config.yaml'
    if not config.exists():
        # Keep generated legacy bridge settings in its own new directory.
        provision('mautrix-discord-native',os.environ['CONTABO_DISCORD_BINARY'],29322,directory)
    data=yaml.safe_load(config.read_text())
    data['bridge']['startup_private_channel_create_limit']=0
    data['bridge']['portal_message_buffer']=8192
    limits=data['bridge'].setdefault('backfill',{}).setdefault('forward_limits',{})
    limits['initial']={'dm':1,'channel':1,'thread':1}
    limits['missed']={'dm':-1,'channel':-1,'thread':-1}
    if data['bridge']['provisioning'].get('shared_secret') in ('generate','disable','',None):
        data['bridge']['provisioning']['shared_secret']=secrets.token_hex(48)
    data['bridge']['provisioning']['prefix']='/_matrix/provision'
    temporary=config.with_suffix('.preparing')
    with temporary.open('w') as stream:
        yaml.safe_dump(data,stream,sort_keys=False)
        stream.flush();os.fsync(stream.fileno())
    os.chmod(temporary,0o640);os.chown(temporary,owner.pw_uid,owner.pw_gid)
    temporary.replace(config)
    activate(build(None,discord=True),['matrix-synapse','mautrix-discord-native','mautrix-whatsapp'])
    data=yaml.safe_load(config.read_text())
    token=data['bridge']['provisioning']['shared_secret']
    base='http://127.0.0.1:29322'+data['bridge']['provisioning']['prefix']
    def api(endpoint,method='GET',payload=None):
        return discord_api(base, token, endpoint, method, payload)
    ping=api('/v1/ping')
    def progress(message,in_progress):
        private_json(STATE/'discord-progress.json', {'import_in_progress':in_progress})
        return message
    discord=ping.get('Discord',ping.get('discord',{}))
    if not discord.get('logged_in'):
        return progress('ACTION REQUIRED: log in with @discord-nativebot:iniyanjoseph.com. Only one pilot DM will import initially.',True)
    if not discord.get('connected'):
        return progress('Discord login is saved but its connection is not ready. Wait for reconnection, then rerun; existing credentials are preserved.',True)
    receiver=discord.get('id')
    if not isinstance(receiver,str) or not receiver.isdecimal():
        raise RuntimeError('Authenticated Discord identity is missing')
    result=api('/v1/contabo/archive','POST')
    pilot=directory/'pilot-channel'
    if not discord_pilot_verified():
        if not pilot.exists():
            return progress('Discord connected; no accessible archived pilot DM could be started.',True)
        expected,found=discord_coverage(snapshot,directory/'bridge.db',[pilot.read_text().strip()],receiver)
        if not expected or found!=expected or result.get('portals_ready',0)!=1:
            return progress(f'Discord pilot import running or blocked: mapped {found}/{expected}. Archive retained; full import not enabled.',True)
        private_json(STATE/'discord-pilot-verified.json', {'expected':expected,'mapped':found,
                     'channel':pilot.read_text().strip(),'receiver':receiver})
        activate(build(None,discord=True,pilot=False),['matrix-synapse','mautrix-discord-native','mautrix-whatsapp'])
        if not wait_for_discord_connection(api):
            return progress('Discord pilot verified; full import enabled, but the saved '
                'Discord connection has not recovered after restart. Inspect the bridge journal; '
                'existing credentials and message mappings are preserved.', True)
    api('/v1/guilds/804408079940583475','POST',{'auto_create_channels':True})
    result=api('/v1/contabo/archive','POST')
    source=sqlite3.connect('file:'+str(snapshot)+'?mode=ro',uri=True)
    try:
        channels=[r[0] for r in source.execute("SELECT id FROM channels WHERE kind IN ('dms','guild:804408079940583475')")]
    finally:
        source.close()
    expected,found=discord_coverage(snapshot,directory/'bridge.db',channels,receiver)
    return progress(f'Discord connected; native mappings {found}/{expected}; inaccessible source/portal attempts '
            f"{result.get('source_or_portal_failures',0)}. Active-thread 403 remains a known source gap. "
            'Client send/receive, replies, encryption recovery and isolated restore remain unverified.',
            found!=expected or result.get('portals_ready',0)!=result.get('portals_started',0) or result.get('source_or_portal_failures',0)>0)


def activate(target, units):
    previous = Path('/run/current-system').resolve()
    run(['nix-env', '--profile', '/nix/var/nix/profiles/system', '--set', target])
    try:
        run([Path(target) / 'bin/switch-to-configuration', 'switch'])
        for unit in units:
            run(['systemctl', 'is-active', '--quiet', unit])
    except Exception:
        run(['nix-env', '--profile', '/nix/var/nix/profiles/system', '--set', previous])
        run([previous / 'bin/switch-to-configuration', 'switch'])
        raise


def install_matrimail_binary(source, directory):
    owner = pwd.getpwnam('matrimail')
    bindir = directory / 'bin'
    if bindir.is_symlink():
        raise RuntimeError('Symlinked Matrimail binary directory refused')
    bindir.mkdir(mode=0o750, exist_ok=True)
    # mkdir's mode is reduced by the worker's 0077 umask. Repair existing
    # installations too: the service needs group traversal of this root-owned
    # directory, while credentials elsewhere in the state directory stay private.
    os.chown(bindir, 0, owner.pw_gid)
    os.chmod(bindir, 0o750)
    binary = bindir / 'matrimail'
    if binary.is_symlink():
        raise RuntimeError('Symlinked Matrimail binary refused')
    if not binary.exists():
        shutil.copy2(source, binary)
    os.chown(binary, 0, owner.pw_gid)
    os.chmod(binary, 0o750)
    return binary


def commission():
    if os.geteuid() != 0 or os.uname().nodename.split('.')[0] != 'contabo':
        raise RuntimeError('Commissioning requires root on Contabo')
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    # First install only disabled service identities. Existing production
    # services retain their data and the WhatsApp linked-device session.
    prepare_identities()
    for network, port in [('gmessages', 29320), ('slack', 29321)]:
        binary = os.environ['CONTABO_' + network.upper() + '_BINARY']
        provision('mautrix-' + network, binary, port, Path('/var/lib/mautrix-' + network))
    run(['runuser', '-u', 'wug', '--', 'bash', HOST / 'email-bridge/build.sh'])
    directory = Path('/var/lib/matrimail')
    # The manually compiled ELF references libolm in the Nix store. Keep its
    # runtime closure alive across garbage collection, scoped to this bridge.
    if not (directory / 'olm-runtime').exists():
        expression = '''let f=builtins.getFlake "/etc/nixos/hosts/contabo";
          p=import f.inputs.nixpkgs {system="x86_64-linux";
            config.permittedInsecurePackages=["olm-3.2.16"];}; in p.olm'''
        run(['nix','build','--impure','--expr',expression,'--out-link',directory/'olm-runtime'])
    binary = install_matrimail_binary(
        Path(pwd.getpwnam('wug').pw_dir) / '.local/share/matrimail-build/matrimail', directory)
    secret = Path('/var/lib/secrets/matrimail.env')
    if not secret.exists():
        with secret.open('x') as stream:
            stream.write('MATRIMAIL_PASSPHRASE=' + secrets.token_hex(48) + '\n')
        os.chmod(secret, 0o600)
    provision('matrimail', binary, 29319, directory)
    activate(build(True), ['matrix-synapse', 'nginx', 'mautrix-whatsapp',
                          'mautrix-gmessages', 'mautrix-slack', 'matrimail'])
    return ('Services deployed; pair @gmessagesbot:iniyanjoseph.com with !gm login google '
            '(the raw Google web/config page is expected: copy its config request as cURL '
            'from browser Network tools and submit only to the private bot DM, then approve on phone), '
            'authenticate each Slack workspace with @slackbot:iniyanjoseph.com, '
            'and use the Matrimail bot login flow for the existing hosted inbox. '
            'Account login, history coverage and send/receive remain unverified.')


def prepare_identities():
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        for name in ('mautrix-gmessages','mautrix-slack','matrimail','mautrix-discord-native'):
            pwd.getpwnam(name)
    except KeyError:
        activate(build(None), ['matrix-synapse','nginx','mautrix-whatsapp','postgresql'])


def secret_file(path):
    if not path.exists():
        with path.open('x') as stream:
            stream.write(secrets.token_hex(48))
        os.chmod(path, 0o600)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError('Secret must be a private regular file')
    value = path.read_text().strip()
    if not value:
        raise RuntimeError('Existing secret is empty; refusing to rotate it silently')
    return value


def commission_mail():
    # Never replace existing MX/forwarding from this script. HTTP proxy IPs
    # cannot receive SMTP, so the mail hostname must resolve to this VPS.
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(
            'mail.iniyanjoseph.com', 443, family=socket.AF_INET)}
    except socket.gaierror:
        raise RuntimeError('Mail hostname has no usable DNS A record; set mail.iniyanjoseph.com to 213.199.55.255') from None
    if addresses != {'213.199.55.255'}:
        raise RuntimeError('Set DNS-only A mail.iniyanjoseph.com to 213.199.55.255 before mail deployment')
    admin = secret_file(Path('/var/lib/secrets/stalwart-admin-password'))
    activate(build(True, mail=True), ['matrix-synapse','mautrix-whatsapp','mautrix-gmessages',
                                    'mautrix-slack','matrimail','stalwart','nginx'])
    auth = base64.b64encode(('admin:' + admin).encode()).decode()
    url = 'https://mail.iniyanjoseph.com/api/principal'
    headers = {'Authorization': 'Basic ' + auth, 'Content-Type':'application/json'}
    def ensure(name, payload):
        try:
            request = urllib.request.Request(url + '/' + name, headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.load(response)
            if 'data' not in result:
                raise RuntimeError('Unexpected Stalwart management response')
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise RuntimeError('Stalwart administrator API authentication/health failed') from None
            if callable(payload):
                payload = payload()
            request = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                             headers=headers, method='POST')
            with urllib.request.urlopen(request, timeout=30) as response:
                if 'data' not in json.load(response):
                    raise RuntimeError('Stalwart rejected principal creation')
    # This is the 0.15.x management API, not the later JMAP management API.
    ensure('iniyanjoseph.com', {'name':'iniyanjoseph.com','type':'domain'})
    def new_mailbox():
        password = secret_file(Path('/var/lib/secrets/stalwart-me-password'))
        hashed = subprocess.run(['openssl','passwd','-6','-stdin'], input=password,
                                capture_output=True, text=True, check=True).stdout.strip()
        return {'name':'me','type':'individual','secrets':[hashed],
                'emails':['me@iniyanjoseph.com'],'roles':['user']}
    ensure('me', new_mailbox)
    return ('Stalwart is deployed and mailbox principal exists. Verify external TCP/25, '
            'PTR, DKIM/SPF/DMARC and inbound/outbound delivery before changing MX or forwarding. '
            'A newly provisioned mailbox password is in /var/lib/secrets/stalwart-me-password; existing credentials are preserved. '
            'Connect Matrimail and the standard mail client to this mailbox; no delivery test has been claimed.')
