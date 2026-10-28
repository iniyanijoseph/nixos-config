import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml
import subprocess
import sqlite3
import json
import shutil
import errno
import http.client
import http.server
import socket
import threading
import io
from contextlib import redirect_stdout

spec = importlib.util.spec_from_file_location('commission', os.environ.get('CONTABO_COMMISSION_SCRIPT',
    str(Path(__file__).with_name('commission-integrations.py'))))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class Tests(unittest.TestCase):
    def test_discord_resumes_post_after_peer_closes_connection_without_response(self):
        requests = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                requests.append((self.path, self.headers.get('Authorization'), body))
                if len(requests) == 1:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"portals_started":120}')
        with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch.object(c.time, 'sleep'), redirect_stdout(io.StringIO()):
                    result = c.discord_api(f'http://127.0.0.1:{server.server_port}',
                        'fixture-token', '/v1/guilds/804408079940583475', 'POST',
                        {'auto_create_channels': True})
            finally:
                server.shutdown()
                thread.join()
        self.assertEqual(result['portals_started'], 120)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0], requests[1])
        self.assertEqual(requests[0][1], 'Bearer fixture-token')

    def test_discord_transport_retry_is_bounded_and_does_not_retry_authentication(self):
        with patch.object(c.urllib.request, 'urlopen', side_effect=http.client.RemoteDisconnected()), \
                patch.object(c.time, 'sleep'), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'POST /v1/contabo/archive failed after 10 attempts'):
                c.discord_api('http://fixture', 'fixture-token', '/v1/contabo/archive', 'POST')
        for code in (401, 403, 409, 500):
            failure = c.urllib.error.HTTPError('http://fixture', code, 'fixture', {}, None)
            with patch.object(c.urllib.request, 'urlopen', side_effect=failure) as opener:
                with self.assertRaises(c.urllib.error.HTTPError):
                    c.discord_api('http://fixture', 'fixture-token', '/v1/contabo/archive', 'POST')
                self.assertEqual(opener.call_count, 1)
        with patch.object(c.urllib.request, 'urlopen', side_effect=http.client.RemoteDisconnected()) as opener:
            with self.assertRaisesRegex(RuntimeError, 'failed after 1 attempts'):
                c.discord_api('http://fixture', 'fixture-token', '/v1/logout', 'POST')
            self.assertEqual(opener.call_count, 1)

    def test_discord_waits_for_saved_login_to_reconnect_after_pilot_restart(self):
        with patch.object(c.time, 'sleep'):
            ping = unittest.mock.Mock(side_effect=[
                {'Discord': {'logged_in': True, 'connected': False}},
                {'Discord': {'logged_in': True, 'connected': True}}])
            self.assertTrue(c.wait_for_discord_connection(ping))
            self.assertEqual(ping.call_count, 2)
            ping = unittest.mock.Mock(return_value={'Discord': {'logged_in': True, 'connected': False}})
            self.assertFalse(c.wait_for_discord_connection(ping))
            self.assertEqual(ping.call_count, 30)

    def test_matrimail_install_repairs_restrictive_umask_and_preserves_existing_binary(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            source = directory / 'built'
            source.write_text('pinned binary')
            owner = type('Owner', (), {'pw_gid':os.getgid()})()
            previous = os.umask(0o077)
            try:
                with patch.object(c.pwd, 'getpwnam', return_value=owner), patch.object(c.os, 'chown'):
                    binary = c.install_matrimail_binary(source, directory)
                    self.assertEqual(binary.parent.stat().st_mode & 0o777, 0o750)
                    self.assertEqual(binary.stat().st_mode & 0o777, 0o750)
                    binary.parent.chmod(0o700)
                    source.write_text('replacement must not overwrite installation')
                    c.install_matrimail_binary(source, directory)
                    self.assertEqual(binary.read_text(), 'pinned binary')
                    self.assertEqual(binary.parent.stat().st_mode & 0o777, 0o750)
            finally:
                os.umask(previous)

    @unittest.skipUnless(os.geteuid() == 0, 'Root required for actual service-identity execution')
    def test_matrimail_executes_as_service_identity_after_repair(self):
        owner = c.pwd.getpwnam('nobody')
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            try:
                os.chown(directory, 0, owner.pw_gid)
            except OSError as error:
                if error.errno in (errno.EINVAL, errno.EPERM):
                    self.skipTest('Runtime cannot assign a separate service identity')
                raise
            directory.chmod(0o750)
            bindir = directory / 'bin'
            bindir.mkdir(mode=0o700)
            binary = bindir / 'matrimail'
            binary.write_text('#!' + shutil.which('sh') + '\nexit 0\n')
            binary.chmod(0o755)
            def execute():
                return subprocess.run([str(binary)], user=owner.pw_uid,
                    group=owner.pw_gid, extra_groups=[], check=True)
            with self.assertRaises(PermissionError):
                execute()
            previous = os.umask(0o077)
            try:
                with patch.object(c.pwd, 'getpwnam', return_value=owner):
                    c.install_matrimail_binary(directory / 'unused-existing-binary', directory)
                    execute()
                    # A clean install must also work under the same private umask.
                    source = directory / 'built'
                    binary.rename(source)
                    bindir.rmdir()
                    c.install_matrimail_binary(source, directory)
                    execute()
            finally:
                os.umask(previous)

    def test_interrupted_or_incomplete_pilot_marker_cannot_promote(self):
        with tempfile.TemporaryDirectory() as d, patch.object(c,'STATE',Path(d)):
            marker=Path(d)/'discord-pilot-verified.json'
            for content in ('', '{', 'null', '{}', '{"expected":3,"mapped":2}'):
                marker.write_text(content)
                self.assertFalse(c.discord_pilot_verified())
            c.private_json(marker, {'expected':3,'mapped':3,'channel':'123','receiver':'456'})
            self.assertTrue(c.discord_pilot_verified())
            self.assertEqual(marker.stat().st_mode & 0o777,0o600)

    def test_archive_must_finish_refresh_before_import(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'source.sqlite'
            with sqlite3.connect(source) as db:
                db.execute('CREATE TABLE channels(kind TEXT,complete INTEGER,refresh_active INTEGER,refreshed_at TEXT,error TEXT)')
                db.execute("INSERT INTO channels VALUES('dms',1,1,'timestamp',NULL)")
            with self.assertRaises(RuntimeError):
                c.validate_discord_snapshot(source)
            with sqlite3.connect(source) as db:
                db.execute('UPDATE channels SET refresh_active=0')
            c.validate_discord_snapshot(source)
            with sqlite3.connect(source) as db:
                db.execute('UPDATE channels SET refreshed_at=NULL')
            with self.assertRaises(RuntimeError):
                c.validate_discord_snapshot(source)

    def test_build_returns_the_built_generation(self):
        with patch.object(c,'run',return_value='/nix/store/fixture-generation\n') as runner:
            self.assertEqual(c.build(True,mail=True,discord=True,pilot=False),'/nix/store/fixture-generation')
        args=runner.call_args.args[0]
        self.assertEqual(args[:2],['nix','build'])
        expression=args[args.index('--expr')+1]
        self.assertIn('contabo.discordNative.enable = lib.mkForce true',expression)
        self.assertIn('contabo.discordNative.pilot = lib.mkForce false',expression)
    @unittest.skipUnless(any(os.environ.get('CONTABO_'+name+'_BINARY') for name in ('GMESSAGES','SLACK','DISCORD','MATRIMAIL')), 'Pinned bridge binaries required')
    def test_real_templates_and_registration_generation(self):
        networks=[]
        for network,port in [('gmessages',29320),('slack',29321)]:
            if os.environ.get('CONTABO_'+network.upper()+'_BINARY'):
                networks.append((network,port))
        if os.environ.get('CONTABO_DISCORD_BINARY'):
            networks.append(('discord',29322))
        if os.environ.get('CONTABO_MATRIMAIL_BINARY'):
            networks.append(('matrimail',29319))
        for network, port in networks:
            binary = os.environ['CONTABO_' + network.upper() + '_BINARY']
            with tempfile.TemporaryDirectory() as d:
                cfg, reg = Path(d)/'config.yaml', Path(d)/'registration.yaml'
                def cli(*args):
                    result=subprocess.run([binary,*args],capture_output=True,text=True)
                    self.assertEqual(result.returncode,0,f'{network} CLI failed: {result.stderr} {result.stdout}')
                cli('-e','-c',str(cfg))
                if network=='discord':
                    original=cfg.read_bytes()
                    retry=subprocess.run([binary,'-e','-c',str(cfg)],capture_output=True)
                    self.assertNotEqual(retry.returncode,0)
                    self.assertEqual(cfg.read_bytes(),original)
                name='discord-native' if network=='discord' else network
                cfg.write_text(c.configure(cfg.read_text(),name,port,d))
                cli('-g','-c',str(cfg),'-r',str(reg))
                registration=yaml.safe_load(reg.read_text())
                self.assertEqual(registration['url'],f'http://127.0.0.1:{port}')
                self.assertTrue(registration['as_token'])
                self.assertTrue(registration['hs_token'])
                self.assertTrue(registration['sender_localpart'])
                self.assertEqual(yaml.safe_load(cfg.read_text())['appservice']['bot']['username'],name+'bot')
                if network == 'gmessages':
                    self.assertEqual(yaml.safe_load(cfg.read_text())['bridge']['command_prefix'], '!gm')

    def test_generated_config_is_private_scoped_and_persistent(self):
        source = {'homeserver': {}, 'appservice': {'bot': {}}, 'database': {},
                  'bridge': {}, 'encryption': {}, 'backfill': {}}
        result = yaml.safe_load(c.configure(yaml.safe_dump(source), 'slack', 29321, '/var/lib/mautrix-slack'))
        self.assertEqual(result['appservice']['hostname'], '127.0.0.1')
        self.assertEqual(result['appservice']['bot']['username'], 'slackbot')
        self.assertEqual(result['bridge']['permissions']['*'], 'block')
        self.assertEqual(result['encryption']['require'], True)
        self.assertEqual(result['database']['uri'], 'file:/var/lib/mautrix-slack/bridge.db?_txlock=immediate')

    def test_unknown_schema_is_not_silently_provisioned(self):
        with self.assertRaises(RuntimeError):
            c.configure('homeserver: {}\nappservice: {}\nbridge: {}', 'slack', 29321, '/tmp/private')

    def test_existing_tokens_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'config.yaml').write_text('existing encryption key')
            (root / 'registration.yaml').write_text('existing appservice token')
            with patch.object(c.pwd, 'getpwnam', return_value=type('Owner', (), {'pw_uid':os.getuid(),'pw_gid':os.getgid()})()), patch.object(c, 'run') as runner:
                c.provision('fixture', '/never/run', 29321, root)
                runner.assert_not_called()
            self.assertEqual((root / 'registration.yaml').read_text(), 'existing appservice token')

    def test_partial_registration_refuses_token_rotation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'config.yaml').write_text('keep this')
            with patch.object(c.pwd, 'getpwnam', return_value=type('Owner', (), {'pw_uid':os.getuid(),'pw_gid':os.getgid()})()):
                with self.assertRaises(RuntimeError):
                    c.provision('fixture', '/never/run', 29321, root)
            self.assertEqual((root / 'config.yaml').read_text(), 'keep this')

    def test_failed_activation_restores_previous_profile(self):
        calls=[]
        def run(args, **kw):
            calls.append([str(x) for x in args])
            if args[0]=='systemctl': raise RuntimeError('unhealthy')
        with patch.object(c, 'run', side_effect=run), patch.object(Path, 'resolve', return_value=Path('/old-generation')):
            with self.assertRaises(RuntimeError): c.activate('/new-generation', ['fixture'])
        self.assertIn(['nix-env','--profile','/nix/var/nix/profiles/system','--set','/old-generation'], calls)
        self.assertEqual(calls[-1], ['/old-generation/bin/switch-to-configuration','switch'])

    def test_archive_mapping_audit_detects_missing_messages(self):
        with tempfile.TemporaryDirectory() as d:
            source,mapping=Path(d)/'source.sqlite',Path(d)/'bridge.sqlite'
            with sqlite3.connect(source) as db:
                db.execute('CREATE TABLE messages(channel_id TEXT,id TEXT,json TEXT)')
                db.executemany('INSERT INTO messages VALUES(?,?,?)',[
                    ('123','100',json.dumps({'type':0})),('123','101',json.dumps({'type':0})),
                    ('123','102',json.dumps({'type':6})),('other','103',json.dumps({'type':0}))])
            with sqlite3.connect(mapping) as db:
                db.execute("CREATE TABLE message(dc_chan_id TEXT,dcid TEXT,dc_chan_receiver TEXT DEFAULT '')")
                db.executemany('INSERT INTO message(dc_chan_id,dcid) VALUES(?,?)',[('123','100'),('123','100'),('other','101')])
            self.assertEqual(c.discord_coverage(source,mapping,['123']),(3,1))
            with sqlite3.connect(mapping) as db:
                db.execute("INSERT INTO message(dc_chan_id,dcid) VALUES('123','101')")
            self.assertEqual(c.discord_coverage(source,mapping,['123']),(3,2))
            with sqlite3.connect(mapping) as db:
                db.execute("INSERT INTO message(dc_chan_id,dcid) VALUES('123','102')")
            self.assertEqual(c.discord_coverage(source,mapping,['123']),(3,3))
            with sqlite3.connect(mapping) as db:
                db.execute("UPDATE message SET dc_chan_receiver='different-account' WHERE dcid='102'")
            self.assertEqual(c.discord_coverage(source,mapping,['123'],'current-account'),(3,2))

if __name__=='__main__': unittest.main()
