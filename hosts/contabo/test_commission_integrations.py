import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

spec = importlib.util.spec_from_file_location('commission', os.environ.get('CONTABO_COMMISSION_SCRIPT',
    str(Path(__file__).with_name('commission-integrations.py'))))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class Tests(unittest.TestCase):
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

if __name__=='__main__': unittest.main()
