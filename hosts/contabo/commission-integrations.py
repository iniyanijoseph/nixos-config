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


def build(enabled):
    expression = '''let f = builtins.getFlake "/etc/nixos/hosts/contabo";
      in (f.nixosConfigurations.contabo.extendModules { modules = [
        ({lib,...}: {contabo.integrations.enable = lib.mkForce %s;})
      ]; }).config.system.build.toplevel''' % ('true' if enabled else 'false')
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
    try:
        for name in ('mautrix-gmessages', 'mautrix-slack', 'matrimail'):
            pwd.getpwnam(name)
    except KeyError:
        activate(build(False), ['matrix-synapse', 'nginx', 'mautrix-whatsapp', 'postgresql'])
    for network, port in [('gmessages', 29320), ('slack', 29321)]:
        binary = os.environ['CONTABO_' + network.upper() + '_BINARY']
        provision('mautrix-' + network, binary, port, Path('/var/lib/mautrix-' + network))
    run(['runuser', '-u', 'wug', '--', 'bash', HOST / 'email-bridge/build.sh'])
    directory = Path('/var/lib/matrimail')
    (directory / 'bin').mkdir(mode=0o750, exist_ok=True)
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
