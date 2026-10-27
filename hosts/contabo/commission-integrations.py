#!/usr/bin/env python3
"""Generate private bridge configurations and deploy a reversible NixOS generation.

No credentials are put in Git or the Nix store. Existing configs/registrations
are preserved. Authentication and message acceptance are reported separately.
"""
import json
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
        pilot = not (STATE/'discord-pilot-verified.json').exists()
    expression = '''let f = builtins.getFlake "/etc/nixos/hosts/contabo";
      in (f.nixosConfigurations.contabo.extendModules { modules = [
        ({lib,...}: {contabo.integrations.enable = lib.mkForce %s;
          contabo.mail.enable = lib.mkForce %s;
          contabo.discordNative.enable = lib.mkForce %s;
          contabo.discordNative.pilot = lib.mkForce %s;})
      ]; }).config.system.build.toplevel''' % ('true' if enabled else 'false', 'true' if mail else 'false', 'true' if discord else 'false', 'true' if pilot else 'false')


def discord_coverage(archive, mapping, channels):
    source=sqlite3.connect('file:'+str(archive)+'?mode=ro',uri=True)
    bridge=sqlite3.connect('file:'+str(mapping)+'?mode=ro',uri=True)
    try:
        expected=found=0
        for channel in channels:
            for (ident,raw) in source.execute('SELECT id,json FROM messages WHERE channel_id=?',(channel,)):
                if json.loads(raw).get('type',0) in (4,5,6):
                    continue
                expected+=1
                if bridge.execute('SELECT 1 FROM message WHERE dc_chan_id=? AND dcid=? LIMIT 1',
                                  (channel,ident)).fetchone():
                    found+=1
        return expected,found
    finally:
        source.close();bridge.close()


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
            if destination.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:
                raise RuntimeError('Discord archive snapshot failed integrity check')
        finally:
            source.close();destination.close()
        os.chmod(temp,0o440);os.chown(temp,0,owner.pw_gid)
        temp.replace(snapshot)
    config=directory/'config.yaml'
    if not config.exists():
        # Keep generated legacy bridge settings in its own new directory.
        provision('mautrix-discord-native',os.environ['CONTABO_DISCORD_BINARY'],29322,directory)
        data=yaml.safe_load(config.read_text())
        data['bridge']['startup_private_channel_create_limit']=0
        data['bridge']['portal_message_buffer']=8192
        data['bridge']['provisioning']['shared_secret']=secrets.token_hex(48)
        data['bridge']['provisioning']['prefix']='/_matrix/provision'
        config.write_text(yaml.safe_dump(data,sort_keys=False))
        os.chmod(config,0o640);os.chown(config,owner.pw_uid,owner.pw_gid)
    activate(build(None,discord=True),['matrix-synapse','mautrix-discord-native','mautrix-whatsapp'])
    data=yaml.safe_load(config.read_text())
    token=data['bridge']['provisioning']['shared_secret']
    base='http://127.0.0.1:29322'+data['bridge']['provisioning']['prefix']
    query='?user_id='+quote('@me:iniyanjoseph.com',safe='')
    def api(endpoint,method='GET',payload=None):
        request=urllib.request.Request(base+endpoint+query,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method=method)
        for attempt in range(30):
            try:
                with urllib.request.urlopen(request,timeout=900) as response:
                    return json.load(response)
            except urllib.error.HTTPError:
                raise
            except urllib.error.URLError:
                if attempt==29:
                    raise
                time.sleep(1)
    ping=api('/v1/ping')
    def progress(message,in_progress):
        target=STATE/'discord-progress.json'
        temporary=target.with_suffix('.tmp')
        with temporary.open('w') as stream:
            json.dump({'import_in_progress':in_progress},stream)
            stream.flush();os.fsync(stream.fileno())
        temporary.replace(target)
        return message
    discord=ping.get('Discord',ping.get('discord',{}))
    if not discord.get('logged_in') or not discord.get('connected'):
        return progress('ACTION REQUIRED: log in with @discord-nativebot:iniyanjoseph.com. Only one pilot DM will import initially.',True)
    result=api('/v1/contabo/archive','POST')
    pilot=directory/'pilot-channel'
    if not (STATE/'discord-pilot-verified.json').exists():
        if not pilot.exists():
            return progress('Discord connected; no accessible archived pilot DM could be started.',True)
        expected,found=discord_coverage(snapshot,directory/'bridge.db',[pilot.read_text().strip()])
        if not expected or found!=expected:
            return progress(f'Discord pilot import running or blocked: mapped {found}/{expected}. Archive retained; full import not enabled.',True)
        (STATE/'discord-pilot-verified.json').write_text(json.dumps({'expected':expected,'mapped':found}))
        activate(build(None,discord=True,pilot=False),['matrix-synapse','mautrix-discord-native','mautrix-whatsapp'])
        api('/v1/guilds/804408079940583475','POST',{'auto_create_channels':True})
        result=api('/v1/contabo/archive','POST')
    source=sqlite3.connect('file:'+str(snapshot)+'?mode=ro',uri=True)
    try:
        channels=[r[0] for r in source.execute("SELECT id FROM channels WHERE kind IN ('dms','guild:804408079940583475')")]
    finally:
        source.close()
    expected,found=discord_coverage(snapshot,directory/'bridge.db',channels)
    return progress(f'Discord connected; native mappings {found}/{expected}; inaccessible source/portal attempts '
            f"{result.get('source_or_portal_failures',0)}. Active-thread 403 remains a known source gap. "
            'Client send/receive, replies, encryption recovery and isolated restore remain unverified.',found!=expected)
    return run(['nix', 'build', '--impure', '--expr', expression,
                '--out-link', STATE / ('connected' if enabled else 'staging'),
                '--print-out-paths'], capture=True).strip()


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
    (directory / 'bin').mkdir(mode=0o750, exist_ok=True)
    # The manually compiled ELF references libolm in the Nix store. Keep its
    # runtime closure alive across garbage collection, scoped to this bridge.
    if not (directory / 'olm-runtime').exists():
        expression = '''let f=builtins.getFlake "/etc/nixos/hosts/contabo";
          p=import f.inputs.nixpkgs {system="x86_64-linux";
            config.permittedInsecurePackages=["olm-3.2.16"];}; in p.olm'''
        run(['nix','build','--impure','--expr',expression,'--out-link',directory/'olm-runtime'])
    binary = directory / 'bin/matrimail'
    if not binary.exists():
        shutil.copy2(Path(pwd.getpwnam('wug').pw_dir) / '.local/share/matrimail-build/matrimail', binary)
        os.chmod(binary, 0o755)
    secret = Path('/var/lib/secrets/matrimail.env')
    if not secret.exists():
        with secret.open('x') as stream:
            stream.write('MATRIMAIL_PASSPHRASE=' + secrets.token_hex(48) + '\n')
        os.chmod(secret, 0o600)
    provision('matrimail', binary, 29319, directory)
    activate(build(True), ['matrix-synapse', 'nginx', 'mautrix-whatsapp',
                          'mautrix-gmessages', 'mautrix-slack', 'matrimail'])
    return ('Services deployed; pair @gmessagesbot:iniyanjoseph.com with login google, '
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
    addresses = {item[4][0] for item in socket.getaddrinfo(
        'mail.iniyanjoseph.com', 443, family=socket.AF_INET)}
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
