"""Offline orchestration tests: no production commands, accounts or files."""
import importlib.util
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    'finish', os.environ.get('CONTABO_FINISH_SCRIPT',
                             str(Path(__file__).with_name('finish-setup.py'))))
finish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(finish)


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = patch.object(finish, 'STATE', Path(self.tmp.name))
        self.state.start()
        self.addCleanup(self.state.stop)
        self.setup = object.__new__(finish.Setup)
        self.setup.results = {}
        self.setup.photos_deferred = False
        self.setup.repair = Mock()
        self.setup.archive = Mock()
        self.setup.remediation = Mock()
        self.setup.integrations = Mock(return_value='service deployment fixture')
        self.setup.mail = Mock(return_value='mail fixture')
        self.setup.discord_native = Mock(return_value='discord fixture')
        self.setup.email_consolidation = Mock(return_value='email audit fixture')
        self.setup.ensure_matrimail_contact_routing = Mock(return_value='contact routing ready')
        self.commission_env = patch.dict(os.environ, {'CONTABO_COMMISSION_SCRIPT': '/offline/mock-commission.py'})
        self.commission_env.start()
        self.addCleanup(self.commission_env.stop)

    def test_failed_backup_never_changes_apps_or_photos(self):
        self.setup.preflight = Mock(return_value='healthy')
        self.setup.backup = Mock(side_effect=RuntimeError('offline'))
        self.setup.photos = Mock()
        self.setup.apps = Mock()
        self.setup.discord = Mock(return_value='inventory')
        self.assertEqual(self.setup.run(), 2)
        self.setup.photos.assert_not_called()
        self.setup.apps.assert_not_called()
        self.setup.discord.assert_called_once()
        status = json.loads((finish.STATE / 'status.json').read_text())
        self.assertEqual(status['Offsite backup']['status'], 'blocked')
        self.assertIn('SETUP INCOMPLETE', (finish.STATE / 'summary.txt').read_text())

    def test_failed_preflight_stops_all_mutations(self):
        self.setup.preflight = Mock(side_effect=RuntimeError('collector active'))
        self.setup.backup = Mock()
        self.assertEqual(self.setup.run(), 2)
        self.setup.backup.assert_not_called()

    def test_rerun_rechecks_real_state_without_trusting_old_success(self):
        self.setup.preflight = Mock(return_value='healthy')
        self.setup.backup = Mock(return_value='backup')
        self.setup.photos = Mock(return_value='photos')
        self.setup.apps = Mock(return_value='apps')
        self.setup.discord = Mock(return_value='inventory')
        self.setup.run()
        self.setup.run()
        self.assertEqual(self.setup.apps.call_count, 2)
        self.assertEqual(self.setup.results['Overall commissioning']['status'], 'blocked')

    def test_email_and_photos_precede_discord_reconciliation(self):
        order=[]
        for name in ('preflight','backup','discord_native','integrations','mail','apps','photos','discord'):
            setattr(self.setup,name,Mock(side_effect=lambda n=name:order.append(n) or n))
        # Simulate an already-deployed Discord archive; it is only inspected
        # after independently verifying email and repairing photos.
        with patch.object(finish, 'DISCORD_NATIVE', Path(self.tmp.name)):
            (Path(self.tmp.name) / 'archive.sqlite').touch()
            (Path(self.tmp.name) / 'bridge.db').touch()
            self.setup.run()
        self.assertLess(order.index('backup'),order.index('integrations'))
        self.assertLess(order.index('integrations'),order.index('photos'))
        self.assertLess(order.index('photos'),order.index('discord_native'))
        self.setup.email_consolidation.assert_called_once()

    def test_disconnected_discord_does_not_block_photos_after_email(self):
        self.setup.discord_import_unverified = True
        for name in ('preflight','backup','discord_native','integrations','mail','apps','photos','discord'):
            setattr(self.setup,name,Mock(return_value='fixture'))
        self.setup.run()
        self.setup.email_consolidation.assert_called_once()
        self.setup.photos.assert_called_once()
        self.assertEqual(self.setup.results['Photo Files dates']['status'], 'done')
        self.assertTrue((finish.STATE / 'photo-after-email-complete').is_file())

    def test_missing_email_consolidation_defers_photos_and_nextcloud(self):
        self.setup.email_consolidation.side_effect = RuntimeError('no contact mappings')
        self.setup.preflight = Mock(return_value='healthy')
        self.setup.backup = Mock(return_value='backup')
        self.setup.photos = Mock()
        self.setup.apps = Mock()
        self.setup.discord = Mock(return_value='inventory')
        self.setup.run()
        self.setup.photos.assert_not_called()
        self.setup.apps.assert_not_called()
        self.assertEqual(self.setup.results['Photo Files dates']['status'], 'deferred')
        self.assertFalse((finish.STATE / 'photo-after-email-complete').exists())

    def test_routing_repair_after_mail_switch_restarts_only_matrimail(self):
        directory = Path(self.tmp.name) / 'matrimail'
        directory.mkdir()
        config = directory / 'config.yaml'
        config.write_text('network:\n  contact_rooms: false\n')
        (directory / '.contact-registration-loaded.json').write_text(
            json.dumps({'sha256': 'loaded-appservice'}))
        module = Mock()
        def apply(home):
            self.assertEqual(home, directory)
            config.write_text('network:\n  contact_rooms: true\n  auto_join_rooms: true\n')
            return True, 'loaded-appservice'
        module.enable_matrimail_contact_rooms.side_effect = apply
        with patch.object(finish, 'MATRIMAIL_HOME', directory), \
             patch.object(finish, 'load_script', return_value=module), \
             patch.object(finish, 'command') as cmd:
            result = finish.Setup.ensure_matrimail_contact_routing(self.setup)
        self.assertIn('verified after its config upgrade', result)
        self.assertEqual(cmd.call_args_list[0].args[0],
                         ['systemctl', 'restart', 'matrimail.service'])
        self.assertEqual(cmd.call_args_list[1].args[0],
                         ['systemctl', 'is-active', '--quiet', 'matrimail.service'])
        self.assertEqual(cmd.call_count, 2)

    def test_routing_repair_detects_matrimail_erasing_config_on_restart(self):
        directory = Path(self.tmp.name) / 'matrimail'
        directory.mkdir()
        config = directory / 'config.yaml'
        config.write_text('network:\n  contact_rooms: false\n')
        (directory / '.contact-registration-loaded.json').write_text(
            json.dumps({'sha256': 'original'}))
        module = Mock()
        def apply(home):
            self.assertEqual(home, directory)
            config.write_text('network:\n  contact_rooms: true\n  auto_join_rooms: true\n')
            return True, 'original'
        module.enable_matrimail_contact_rooms.side_effect = apply
        def invoke(args, **kw):
            if args == ['systemctl', 'restart', 'matrimail.service']:
                # Simulate the former binary's upgrade stripping unknown keys.
                config.write_text('network:\n  imap: {}\n')
        with patch.object(finish, 'MATRIMAIL_HOME', directory), \
             patch.object(finish, 'load_script', return_value=module), \
             patch.object(finish, 'command', side_effect=invoke):
            with self.assertRaisesRegex(RuntimeError, 'discarded contact routing'):
                finish.Setup.ensure_matrimail_contact_routing(self.setup)

    def test_routing_repair_is_idempotent_and_preserves_registration_guard(self):
        directory = Path(self.tmp.name) / 'matrimail'
        directory.mkdir()
        (directory / 'config.yaml').write_text('network:\n  contact_rooms: true\n')
        marker = directory / '.contact-registration-loaded.json'
        marker.write_text(json.dumps({'sha256': 'original'}))
        module = Mock()
        module.enable_matrimail_contact_rooms.return_value = False, 'original'
        with patch.object(finish, 'MATRIMAIL_HOME', directory), \
             patch.object(finish, 'load_script', return_value=module), \
             patch.object(finish, 'command') as cmd:
            self.assertIn('enabled', finish.Setup.ensure_matrimail_contact_routing(self.setup))
            cmd.assert_not_called()
            module.enable_matrimail_contact_rooms.return_value = True, 'unexpected-change'
            with self.assertRaisesRegex(RuntimeError, 'registration changed'):
                finish.Setup.ensure_matrimail_contact_routing(self.setup)
            cmd.assert_not_called()

    def test_duplicate_systemd_start_skips_without_running_setup(self):
        # Activation of the timer and boot-resume unit during NixOS switch
        # must not race the original worker through its nonblocking lock.
        with patch.object(finish.os, 'geteuid', return_value=0), \
             patch.object(finish.os, 'uname', return_value=Mock(nodename='contabo')), \
             patch.object(finish.fcntl, 'flock', side_effect=BlockingIOError), \
             patch.object(finish, 'Setup', side_effect=AssertionError('must not run')), \
             patch.object(finish.sys, 'argv', ['contabo-finish-setup']):
            self.assertEqual(finish.main(), 0)
        self.assertFalse((finish.STATE / 'photo-after-email-complete').exists())

    def test_email_audit_cannot_certify_unpopulated_contact_rooms(self):
        # The old bridge may have lost its legacy portal mappings. Zero
        # legacy rows is not evidence that the client's old rooms are gone.
        report = {'contact_routing_enabled': True, 'bridge_logins': 1,
                  'contact_rooms': 0, 'contact_message_parts': 0,
                  'legacy_rooms': 0, 'legacy_message_parts': 0,
                  'legacy_parts_with_contact_mappings': 0,
                  'archived_legacy_rooms': 0}
        module = Mock()
        module.mail_consolidation_status.return_value = report
        with patch.dict(os.environ, {'CONTABO_ADMIN_SCRIPT': '/offline/admin.py'}), \
             patch.object(finish, 'load_script', return_value=module):
            with self.assertRaisesRegex(RuntimeError, 'No populated contact'):
                finish.Setup.email_consolidation(self.setup)
            report['contact_rooms'] = 1
            report['contact_message_parts'] = 1
            self.assertIn('Contact-room audit passed', finish.Setup.email_consolidation(self.setup))
        self.assertTrue((finish.STATE / 'mail-consolidation.json').is_file())

    def test_post_mail_retry_never_modifies_photos_before_verified_email(self):
        self.setup.preflight = Mock(return_value='healthy')
        self.setup.backup = Mock(return_value='backup')
        self.setup.photos = Mock(return_value='photos')
        self.setup.apps = Mock(return_value='apps')
        self.setup.email_consolidation.side_effect = RuntimeError('mail not ready')
        self.assertEqual(self.setup.after_email(), 2)
        self.setup.photos.assert_not_called()
        self.setup.backup.assert_not_called()
        self.setup.email_consolidation.side_effect = None
        self.assertEqual(self.setup.after_email(), 0)
        self.setup.photos.assert_called_once()
        self.setup.apps.assert_called_once()
        self.assertTrue((finish.STATE / 'photo-after-email-complete').exists())
        self.assertEqual(self.setup.after_email(), 0)
        self.assertEqual(self.setup.photos.call_count, 1)

    def test_photo_stage_requires_app_checks_to_mark_complete(self):
        self.setup.preflight = Mock(return_value='healthy')
        self.setup.backup = Mock(return_value='backup')
        self.setup.photos = Mock(return_value='photos')
        self.setup.apps = Mock(side_effect=RuntimeError('apps unavailable'))
        self.assertEqual(self.setup.after_email(), 2)
        self.assertFalse((finish.STATE / 'photo-after-email-complete').exists())

    def test_completed_discord_native_import_is_never_replayed_on_setup_rerun(self):
        directory = Path(self.tmp.name) / 'discord-native'
        directory.mkdir()
        snapshot, mapping = directory / 'archive.sqlite', directory / 'bridge.db'
        with sqlite3.connect(snapshot) as db:
            db.execute('CREATE TABLE channels (id TEXT,kind TEXT)')
            db.execute("INSERT INTO channels VALUES ('123','dms')")
        mapping.touch()
        (finish.STATE / 'discord-pilot-verified.json').write_text('{"receiver":"456"}')
        module = Mock()
        module.STATE = finish.STATE
        module.discord_pilot_verified.return_value = True
        module.discord_coverage.return_value = (3, 3)
        with patch.object(finish, 'DISCORD_NATIVE', directory), \
             patch.object(finish, 'load_script', return_value=module):
            detail = finish.Setup.discord_native(self.setup)
        self.assertIn('preserved', detail)
        self.assertEqual(self.setup.results['Discord historical mapping coverage']['status'], 'done')
        module.commission_discord.assert_not_called()
        module.discord_coverage.assert_called_once_with(snapshot, mapping, ['123'], '456')

    def test_unverified_discord_native_import_is_not_restarted(self):
        directory = Path(self.tmp.name) / 'discord-native'
        directory.mkdir()
        snapshot, mapping = directory / 'archive.sqlite', directory / 'bridge.db'
        with sqlite3.connect(snapshot) as db:
            db.execute('CREATE TABLE channels (id TEXT,kind TEXT)')
            db.execute("INSERT INTO channels VALUES ('123','dms')")
        mapping.touch()
        module = Mock()
        module.STATE = finish.STATE
        module.discord_pilot_verified.return_value = False
        module.discord_coverage.return_value = (3, 1)
        with patch.object(finish, 'DISCORD_NATIVE', directory), \
             patch.object(finish, 'load_script', return_value=module):
            finish.Setup.discord_native(self.setup)
        self.assertEqual(self.setup.results['Discord historical mapping coverage']['status'], 'blocked')
        module.commission_discord.assert_not_called()
        module.discord_coverage.assert_called_once_with(snapshot, mapping, ['123'], None)

    def test_audit_cannot_treat_partial_scan_as_success(self):
        text = ('Media files found: 100\nSample: 100\nExif inspected: 50\n'
                'exif_batch_errors: 1\nexif_decode_errors: 0\n')
        with self.assertRaises(RuntimeError):
            finish.parse_counts(text)
        with self.assertRaises(RuntimeError):
            finish.parse_counts('Media files found: 100\n')

    def test_photo_conflicts_do_not_block_unrelated_files(self):
        plan = {'metadata': [], 'mtimes': [],
                'exceptions': [{'reason': 'embedded_date_conflict', 'rel': 'private.jpg'}]}
        self.setup.remediation.plan.return_value = plan
        with patch.object(finish, 'command', return_value='audit'), \
             patch.object(finish, 'parse_counts', return_value={}):
            self.setup.photos()
        self.setup.repair.apply.assert_not_called()
        self.setup.repair.scoped_scan.assert_called_once()
        self.assertEqual(self.setup.results['Photo metadata exceptions']['status'], 'blocked')

    def test_photo_pilot_postcondition_blocks_remaining_batch(self):
        rows = list(range(30))
        self.setup.remediation.plan.side_effect = [
            {'metadata': [], 'mtimes': rows, 'exceptions': []},
            {'metadata': []}, {'metadata': []},
            {'mtimes': rows}, {'mtimes': list(range(15))}]
        with patch.object(finish, 'command', return_value='audit'), \
             patch.object(finish, 'parse_counts', return_value={}):
            with self.assertRaises(RuntimeError):
                self.setup.photos()
        self.setup.repair.apply.assert_called_once_with(rows, 20)

    def test_failed_missing_date_transform_does_not_block_independent_mtimes(self):
        missing = {'file_type': 'JPEG', 'rel': 'missing.jpg'}
        safe = {'rel': 'safe.jpg'}
        self.setup.remediation.plan.side_effect = [
            {'metadata': [missing], 'mtimes': [safe], 'exceptions': []},
            {'mtimes': [safe]}, {'mtimes': []},
            {'mtimes': [], 'metadata': [missing], 'exceptions': []}]
        self.setup.remediation.apply_metadata.side_effect = RuntimeError('checksum failed')
        with patch.object(finish, 'command', return_value='audit'), \
             patch.object(finish, 'parse_counts', return_value={}):
            self.setup.photos()
        self.setup.repair.apply.assert_any_call([safe], 20)
        self.assertEqual(self.setup.results['Missing capture dates']['status'], 'blocked')
        self.assertEqual(self.setup.results['Photo metadata exceptions']['status'], 'blocked')

    def test_apps_preserve_enabled_versions_enable_disabled_install_missing(self):
        states = [
            {'enabled': {'calendar': '1'}, 'disabled': {'contacts': '2'}},
            {'enabled': {'calendar': '1'}, 'disabled': {'contacts': '2'}},
            {'enabled': {'calendar': '1', 'contacts': '2'}},
            {'enabled': {'calendar': '1', 'contacts': '2'}},
            {'enabled': {'calendar': '1', 'contacts': '2', 'tasks': '3'}},
            {'enabled': {'calendar': '1', 'contacts': '2', 'tasks': '3'}},
        ]
        actions = []
        def run(args, **kwargs):
            if args[1] == 'app:list':
                return json.dumps(states.pop(0))
            actions.append(args[1:])
        with patch.object(finish, 'command', side_effect=run):
            self.setup.apps()
        self.assertEqual(actions, [['app:enable', 'contacts'], ['app:install', 'tasks']])


if __name__ == '__main__':
    unittest.main()
