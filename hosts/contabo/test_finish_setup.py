"""Offline orchestration tests: no production commands, accounts or files."""
import importlib.util
import json
import os
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
        self.setup.repair = Mock()
        self.setup.archive = Mock()

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
        self.assertEqual(self.setup.results['Discord history and live cutover']['status'], 'blocked')

    def test_audit_cannot_treat_partial_scan_as_success(self):
        text = ('Media files found: 100\nSample: 100\nExif inspected: 50\n'
                'exif_batch_errors: 1\nexif_decode_errors: 0\n')
        with self.assertRaises(RuntimeError):
            finish.parse_counts(text)
        with self.assertRaises(RuntimeError):
            finish.parse_counts('Media files found: 100\n')

    def test_photo_conflicts_do_not_trigger_repair(self):
        counts = {'embedded_date_conflicts_with_takeout': 4}
        with patch.object(finish, 'command', return_value='audit'), \
             patch.object(finish, 'parse_counts', return_value=counts):
            with self.assertRaises(RuntimeError):
                self.setup.photos()
        self.setup.repair.apply.assert_not_called()

    def test_photo_pilot_postcondition_blocks_remaining_batch(self):
        rows = list(range(30))
        self.setup.repair.inventory.side_effect = [
            (rows, {'unsafe_files': 0, 'nonregular_or_hardlinked': 0}),
            (list(range(15)), {})]
        with patch.object(finish, 'command', return_value='audit'), \
             patch.object(finish, 'parse_counts', return_value={}):
            with self.assertRaises(RuntimeError):
                self.setup.photos()
        self.setup.repair.apply.assert_called_once_with(rows, 20)

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
