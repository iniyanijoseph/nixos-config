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

spec = importlib.util.spec_from_file_location('commission', os.environ.get('CONTABO_COMMISSION_SCRIPT',
    str(Path(__file__).with_name('commission-integrations.py'))))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class Tests(unittest.TestCase):
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
                subprocess.run([binary,'-e','-c',str(cfg)],check=True,capture_output=True)
                cfg.write_text(c.configure(cfg.read_text(),network,port,d))
                subprocess.run([binary,'-g','-c',str(cfg),'-r',str(reg)],check=True,capture_output=True)
                registration=yaml.safe_load(reg.read_text())
                self.assertEqual(registration['url'],f'http://127.0.0.1:{port}')
                self.assertTrue(registration['as_token'])
                self.assertTrue(registration['hs_token'])

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
