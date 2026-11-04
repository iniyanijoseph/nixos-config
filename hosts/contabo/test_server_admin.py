import csv
from datetime import datetime, timezone
import importlib.util
import io
import json
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

script = Path(os.environ.get('CONTABO_SERVER_ADMIN_SCRIPT', Path(__file__).with_name('server-admin.py')))
spec = importlib.util.spec_from_file_location('server_admin', script)
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)


class Tests(unittest.TestCase):
    def test_invitation_is_single_use_random_and_expiring(self):
        requests = []
        def api(path, token, body):
            requests.append((path, token, body)); return body
        with patch.object(c, 'api', side_effect=api):
            first, expiry = c.invite(72, token='private-admin', now=100)
            second, _ = c.invite(72, token='private-admin', now=100)
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith('https://matrix.iniyanjoseph.com/invite/#token='))
        self.assertEqual(expiry, (100 + 72*3600)*1000)
        self.assertEqual(requests[0][2]['uses_allowed'], 1)
        self.assertGreaterEqual(len(requests[0][2]['token']), 40)
        self.assertNotIn('private-admin', first)

    def test_invitation_rejects_unconfirmed_unlimited_registration(self):
        with patch.object(c, 'api', return_value={'uses_allowed': None}):
            with self.assertRaisesRegex(RuntimeError, 'single-use'):
                c.invite(token='private', now=0)

    def test_zero_days_and_warmup_are_in_seven_day_average(self):
        rows = [dict(room_id='!one', room_name='One', day=day, sender=sender, messages=str(count))
                for day, sender, count in [('2026-10-22', '@warmup', 7),
                                          ('2026-10-28', '@a', 7),
                                          ('2026-11-03', '@a', 3),
                                          ('2026-11-03', '@b', 1)]]
        result = c.aggregate(rows, 7, 'UTC', datetime(2026, 11, 3, 12, tzinfo=timezone.utc))
        room = result['rooms'][0]
        self.assertEqual([day['count'] for day in room['days']], [7,0,0,0,0,0,4])
        self.assertEqual(room['days'][0]['average'], 2)
        self.assertAlmostEqual(room['days'][-1]['average'], 11/7)
        self.assertEqual(room['total'], 11)
        self.assertEqual(room['people'][0]['count'], 10)
        self.assertAlmostEqual(sum(person['ratio'] for person in room['people']), 1)
        self.assertNotIn('@warmup', str(room['people']))

    def test_query_escapes_room_and_never_extracts_bodies(self):
        sql = c.stats_query(1, 2, 'America/New_York', "!room'; DROP TABLE events; --")
        self.assertIn("e.room_id='!room''; DROP TABLE events; --'", sql)
        self.assertIn("'m.replace'", sql)
        self.assertNotIn("->>'body'", sql)
        with self.assertRaises(ValueError):
            c.make_stats(days=367)

    def test_room_names_cannot_break_out_of_report_data(self):
        html = c.render_stats({'rooms': [{'name': '</script><script>bad()</script>'}]}, '<script>const data=/*CONTABO_DATA*/null;</script>')
        self.assertEqual(html.count('</script>'), 1)
        self.assertIn('\\u003c/script\\u003e', html)

    def test_whatsapp_secret_preserves_existing_encryption_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'whatsapp.env'
            path.write_text('WHATSAPP_PICKLE_KEY=unchanged\n'); path.chmod(0o600)
            self.assertTrue(c.ensure_whatsapp_secret(path))
            after = path.read_text()
            self.assertIn('WHATSAPP_PICKLE_KEY=unchanged\n', after)
            self.assertFalse(c.ensure_whatsapp_secret(path))
            self.assertEqual(path.read_text(), after)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, 'permissions'):
                c.ensure_whatsapp_secret(path)

    def test_whatsapp_health_probe_resolves_only_protected_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / 'whatsapp.env'
            secret = 'private-' + 'a' * 48
            env.write_text('WHATSAPP_PICKLE_KEY=unchanged\nWHATSAPP_PROVISIONING_SECRET=' + secret + '\n')
            env.chmod(0o600)
            self.assertEqual(c.bridge_provisioning_secret(
                'whatsapp', '$WHATSAPP_PROVISIONING_SECRET', env), secret)
            self.assertEqual(c.bridge_provisioning_secret(
                'whatsapp', 'already-expanded', env), 'already-expanded')
            self.assertEqual(c.bridge_provisioning_secret(
                'slack', '$WHATSAPP_PROVISIONING_SECRET', env), '$WHATSAPP_PROVISIONING_SECRET')
            env.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, 'Unsafe private file permissions'):
                c.bridge_provisioning_secret('whatsapp', '$WHATSAPP_PROVISIONING_SECRET', env)
            env.chmod(0o600)
            env.write_text('WHATSAPP_PICKLE_KEY=unchanged\n')
            with self.assertRaisesRegex(RuntimeError, 'missing or invalid'):
                c.bridge_provisioning_secret('whatsapp', '$WHATSAPP_PROVISIONING_SECRET', env)

    def test_mail_consolidation_audit_is_read_only_and_account_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config.yaml'
            db_path = root / 'matrimail.db'
            config.write_text('network:\n  contact_rooms: true\ndatabase:\n  uri: file:' +
                              str(db_path) + '?_fk=1\n')
            config.chmod(0o600)
            with sqlite3.connect(db_path) as db:
                db.execute('CREATE TABLE portal (id TEXT, mxid TEXT)')
                db.execute('CREATE TABLE message (bridge_id TEXT, room_receiver TEXT, id TEXT, part_id TEXT, room_id TEXT, mxid TEXT)')
                db.execute('CREATE TABLE email_accounts (id TEXT)')
                db.execute('CREATE TABLE user_login (id TEXT)')
                db.execute('INSERT INTO user_login VALUES (\'email:example\')')
                db.execute('INSERT INTO email_accounts VALUES (\'example\')')
                db.execute('INSERT INTO portal VALUES (\'thread:old\',\'!old:example.com\')')
                db.execute('INSERT INTO message VALUES (\'mail\',\'email:example\',\'email:m1\',\'text\',\'thread:old\',\'$legacy\')')
            status = c.mail_consolidation_status(root)
            self.assertEqual(status['legacy_rooms'], 1)
            self.assertEqual(status['contact_rooms'], 0)
            self.assertEqual(status['legacy_parts_with_contact_mappings'], 0)
            self.assertIn('No populated contact rooms', status['assessment'])
            with sqlite3.connect(db_path) as db:
                db.execute('INSERT INTO portal VALUES (\'contact:alice\',\'!new:example.com\')')
                db.execute('INSERT INTO message VALUES (\'mail\',\'email:example\',\'contact-email:m1\',\'text\',\'contact:alice\',\'$new\')')
                db.execute('INSERT INTO message VALUES (\'mail\',\'other-account\',\'contact-email:m1\',\'attachment\',\'contact:alice\',\'$other\')')
            status = c.mail_consolidation_status(root)
            self.assertEqual(status['legacy_parts_with_contact_mappings'], 1)
            self.assertEqual(status['contact_message_parts'], 2)
            self.assertIn('not all marked as archived', status['assessment'])
            with sqlite3.connect(db_path) as db:
                db.execute('CREATE TABLE contabo_legacy_mail_retirement (portal_id TEXT)')
                db.execute('INSERT INTO contabo_legacy_mail_retirement VALUES (\'thread:old\')')
            self.assertIn('appear complete', c.mail_consolidation_status(root)['assessment'])
            self.assertNotIn('email:example', str(status))
            self.assertNotIn('!new:example.com', str(status))
            # The audit must not update source message mappings or room names.
            with sqlite3.connect(db_path) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM message').fetchone()[0], 3)

    def test_legacy_room_prune_is_owner_scoped_verified_and_preview_first(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / 'matrimail'
            home.mkdir()
            db_path = home / 'bridge.db'
            config = home / 'config.yaml'
            config.write_text('network:\n  contact_rooms: true\ndatabase:\n  uri: file:' +
                              str(db_path) + '\n')
            config.chmod(0o600)
            cursors = home / 'contabo-backfill-contacts-v2'
            cursors.mkdir()
            cp = cursors / 'full.json'
            cp.write_text(json.dumps({'waterline': 20, 'after': 20}))
            cp.chmod(0o600)
            with sqlite3.connect(db_path) as db:
                db.execute('CREATE TABLE portal (bridge_id TEXT, id TEXT, receiver TEXT, mxid TEXT)')
                db.execute('CREATE TABLE message (bridge_id TEXT, room_receiver TEXT, id TEXT, part_id TEXT, room_id TEXT, mxid TEXT)')
                db.execute('CREATE TABLE user_login (bridge_id TEXT, user_mxid TEXT, id TEXT)')
                db.execute('CREATE TABLE contabo_legacy_mail_retirement (bridge_id TEXT, receiver TEXT, portal_id TEXT)')
                db.execute("INSERT INTO user_login VALUES ('mail', ?, 'email:mine')", (c.OWNER,))
                db.execute("INSERT INTO user_login VALUES ('mail', '@friend:iniyanjoseph.com', 'email:friend')")
                db.executemany('INSERT INTO portal VALUES (?,?,?,?)', [
                    ('mail','thread:mine','email:mine','!old:iniyanjoseph.com'),
                    ('mail','thread:friend','email:friend','!friend:iniyanjoseph.com'),
                    ('mail','contact:alice','email:mine','!new:iniyanjoseph.com'),
                ])
                db.executemany('INSERT INTO message VALUES (?,?,?,?,?,?)', [
                    ('mail','email:mine','email:old','text','thread:mine','$old'),
                    ('mail','email:mine','contact-email:old','text','contact:alice','$new'),
                    ('mail','email:friend','email:friend','text','thread:friend','$friendold'),
                    ('mail','email:friend','contact-email:friend','text','contact:alice','$friendnew'),
                ])
                db.executemany('INSERT INTO contabo_legacy_mail_retirement VALUES (?,?,?)', [
                    ('mail','email:mine','thread:mine'),
                    ('mail','email:friend','thread:friend')
                ])
            self.assertEqual(c.matrimail_legacy_cleanup_candidates(home), ['!old:iniyanjoseph.com'])
            private = root / 'private'
            backup = root / 'backup.json'
            with patch.object(c, 'api', side_effect=AssertionError('preview must never use Synapse')):
                preview = c.prune_matrimail_legacy_rooms(home, private, backup_path=backup)
            self.assertEqual(preview['eligible_not_submitted'], 1)
            self.assertEqual(preview['next_batch'], ['!old:iniyanjoseph.com'])
            with patch.object(c, 'admin_token', side_effect=AssertionError('no backup, no credential read')):
                with self.assertRaisesRegex(RuntimeError, 'fresh, verified'):
                    c.prune_matrimail_legacy_rooms(home, private, apply=True, backup_path=backup)
            backup.write_text('{}')
            requests = []
            def api(path, token, body=None, method=None):
                requests.append((path, token, body, method))
                return {'delete_id': 'accepted-1'}
            with patch.object(c, 'admin_token', return_value='admin-token'), patch.object(c, 'api', side_effect=api):
                submitted = c.prune_matrimail_legacy_rooms(home, private, apply=True, backup_path=backup)
                again = c.prune_matrimail_legacy_rooms(home, private, apply=True, backup_path=backup)
            self.assertEqual(submitted['submitted'], ['!old:iniyanjoseph.com'])
            self.assertEqual(again['submitted'], [])
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0][3], 'DELETE')
            self.assertEqual(requests[0][2], {'block': True, 'purge': True})
            self.assertNotIn('friend', str(submitted))
            self.assertNotIn('!new', str(submitted))
            cp.write_text(json.dumps({'waterline': 20, 'after': 19}))
            cp.chmod(0o600)
            with self.assertRaisesRegex(RuntimeError, 'checkpoint'):
                c.matrimail_legacy_cleanup_candidates(home)
            with sqlite3.connect(db_path) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM portal').fetchone()[0], 3)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM message').fetchone()[0], 4)

    def test_v3_auto_rebuild_deletes_only_verified_owner_old_rooms(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / 'matrimail'
            home.mkdir()
            dbpath = home / 'bridge.db'
            cfg = home / 'config.yaml'
            cfg.write_text('network:\\n  contact_rooms: true\\ndatabase:\\n  uri: file:' + str(dbpath) + '\\n')
            cfg.chmod(0o600)
            receiver = 'email:owner@gmail.com'
            digest = hashlib.sha256(receiver.encode()).hexdigest()
            cpdir = home / 'contabo-backfill-contacts-v3'
            cpdir.mkdir()
            cursor = 'a' * 64 + '.json'
            checkpoint = cpdir / cursor
            checkpoint.write_text(json.dumps({'version': 1, 'uid_validity': 100,
                                              'after': 120, 'waterline': 120}))
            checkpoint.chmod(0o600)
            scope = cpdir / ('scope-' + digest + '.json')
            source = {'version': 3, 'account_hash': digest, 'complete': True,
                      'folders': ['[Gmail]/All Mail'], 'cursor_files': [cursor]}
            scope.write_text(json.dumps(source))
            scope.chmod(0o600)
            with sqlite3.connect(dbpath) as db:
                db.execute('CREATE TABLE portal (bridge_id TEXT, id TEXT, receiver TEXT, mxid TEXT)')
                db.execute('CREATE TABLE message (bridge_id TEXT, room_receiver TEXT, id TEXT, part_id TEXT, room_id TEXT, mxid TEXT)')
                db.execute('CREATE TABLE user_login (bridge_id TEXT, user_mxid TEXT, id TEXT)')
                db.execute('CREATE TABLE contabo_mail_v3_retirement (bridge_id TEXT, receiver TEXT, portal_id TEXT)')
                db.executemany('INSERT INTO user_login VALUES (?,?,?)',
                    [('mail', c.OWNER, receiver), ('mail', '@friend:iniyanjoseph.com', 'email:friend@gmail.com')])
                db.executemany('INSERT INTO portal VALUES (?,?,?,?)', [
                    ('mail','thread:old',receiver,'!old:iniyanjoseph.com'),
                    ('mail','contact:misgrouped',receiver,'!misgrouped:iniyanjoseph.com'),
                    ('mail','contact-v3:alice',receiver,'!new:iniyanjoseph.com'),
                    ('mail','thread:friend','email:friend@gmail.com','!friend:iniyanjoseph.com')])
                db.executemany('INSERT INTO message VALUES (?,?,?,?,?,?)', [
                    ('mail',receiver,'email:one','text','thread:old','$old1'),
                    ('mail',receiver,'email:one','attachment','thread:old','$old2'),
                    ('mail',receiver,'contact-email:two','text','contact:misgrouped','$old3'),
                    ('mail',receiver,'contact-v3-email:one','text','contact-v3:alice','$new1'),
                    ('mail',receiver,'contact-v3-email:one','attachment','contact-v3:alice','$new2'),
                    ('mail',receiver,'contact-v3-email:two','text','contact-v3:alice','$new3'),
                    ('mail','email:friend@gmail.com','email:friend','text','thread:friend','$other')])
                db.executemany('INSERT INTO contabo_mail_v3_retirement VALUES (?,?,?)',[
                    ('mail',receiver,'thread:old'),('mail',receiver,'contact:misgrouped')])
            verified = c.matrimail_v3_rebuild_status(home)
            self.assertTrue(verified['ready'])
            self.assertEqual(verified['eligible_rooms'], 2)
            self.assertEqual(verified['verified_v3_parts'], 3)
            self.assertNotIn('!friend', str(verified))
            private = root / 'private'
            backup = root / 'backup.json'
            with patch.object(c, 'api', side_effect=AssertionError('preview only')):
                preview = c.matrimail_auto_rebuild_cleanup(home, private, backup_path=backup)
            self.assertEqual(preview['status'], 'preview')
            self.assertEqual(preview['pending'], 2)
            with patch.object(c, 'admin_token', side_effect=AssertionError('no backup')):
                deferred = c.matrimail_auto_rebuild_cleanup(home, private, backup, apply=True)
            self.assertEqual(deferred['status'], 'deferred')
            backup.write_text('{}')
            c.atomic_private(private / 'admin-session.json', '{}')
            calls = []
            def api(path, token, body=None, method=None):
                calls.append((path, method, body))
                if method == 'DELETE':
                    return {'delete_id': 'accepted-' + str(len(calls))}
                return {'status': 'complete'}
            with patch.object(c, 'admin_token', return_value='admin'), patch.object(c, 'api', side_effect=api):
                done = c.matrimail_auto_rebuild_cleanup(home, private, backup, apply=True)
                again = c.matrimail_auto_rebuild_cleanup(home, private, backup, apply=True)
            self.assertEqual(done['status'], 'complete')
            self.assertEqual(again['submitted_now'], 0)
            deletes = [x for x in calls if x[1] == 'DELETE']
            self.assertEqual(len(deletes), 2)
            self.assertTrue(all('/_synapse/admin/v2/rooms/%21' in x[0] for x in deletes))
            self.assertTrue(all(x[2] == {'block': True, 'purge': True} for x in deletes))
            with sqlite3.connect(dbpath) as db:
                db.execute("DELETE FROM message WHERE id='contact-v3-email:one' AND part_id='attachment'")
            status = c.matrimail_v3_rebuild_status(home)
            self.assertFalse(status['ready'])
            self.assertEqual(status['blocked_rooms'], 1)
            scope.write_text(json.dumps({**source, 'complete': False}))
            self.assertFalse(c.matrimail_v3_rebuild_status(home)['ready'])

    def test_mapping_proof_requires_both_recent_directions(self):
        events = [{'sender': c.OWNER, 'timestamp': '1000000'}, {'sender': '@other', 'timestamp': '999999'}]
        self.assertTrue(c.mapping_proof(events, now=1000, minutes=1)['recent_both_directions'])
        self.assertFalse(c.mapping_proof(events[:1], now=1000, minutes=1)['recent_both_directions'])
        self.assertFalse(c.mapping_proof(events, now=2000, minutes=1)['recent_both_directions'])

    def test_native_mapping_inspection_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bridge.db'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE message (mxid TEXT)')
                db.executemany('INSERT INTO message VALUES (?)', [('$real',), ('~fake:bad',)])
            before = path.read_bytes()
            self.assertEqual(c.sqlite_mappings(path), ['$real'])
            self.assertEqual(path.read_bytes(), before)

    def test_cleanup_plan_makes_no_changes(self):
        with patch.object(c.subprocess, 'run') as run, patch.object(c.shutil, 'rmtree') as remove:
            with patch('sys.stdout', new=io.StringIO()):
                c.cleanup()
            run.assert_not_called(); remove.assert_not_called()


@unittest.skipUnless(shutil.which('initdb') and shutil.which('pg_ctl') and os.geteuid() != 0,
                     'PostgreSQL fixture runs in pinned Nix CI as an unprivileged user')
class PostgreSQLQuery(unittest.TestCase):
    def test_real_postgres_counts_filter_edits_outliers_and_rooms(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory); data = directory / 'db'
            subprocess.run(['initdb','-D',str(data),'-A','trust','-U','postgres','--no-locale','-E','UTF8'], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(['pg_ctl','-D',str(data),'-l',str(directory/'log'),'-o',f"-k {directory} -h ''",'-w','start'], check=True, stdout=subprocess.DEVNULL)
            try:
                def sql(text):
                    return subprocess.run(['psql','-X','-q','-h',str(directory),'-U','postgres','-d','postgres','-v','ON_ERROR_STOP=1'], input=text, text=True, check=True, capture_output=True).stdout
                sql('''CREATE TABLE events (event_id TEXT,room_id TEXT,sender TEXT,type TEXT,outlier BOOLEAN,origin_server_ts BIGINT);
                CREATE TABLE room_stats_state (room_id TEXT,name TEXT);
                CREATE TABLE event_json (event_id TEXT,json TEXT);
                INSERT INTO room_stats_state VALUES ('!one','One'),('!two','Two');
                INSERT INTO events VALUES ('$a','!one','@a','m.room.encrypted',false,1793707200000),
                  ('$b','!one','@b','m.room.message',false,1793707200000),
                  ('$edit','!one','@b','m.room.message',false,1793707200000),
                  ('$outlier','!one','@a','m.room.message',true,1793707200000),
                  ('$member','!one','@a','m.room.member',false,1793707200000),
                  ('$other','!two','@c','m.room.message',false,1793707200000);
                INSERT INTO event_json VALUES ('$edit','{"content":{"m.relates_to":{"rel_type":"m.replace"}}}');''')
                query = c.stats_query(1793700000000,1793800000000,'UTC','!one')
                rows = list(csv.DictReader(io.StringIO(sql('BEGIN READ ONLY;'+query+'COMMIT;'))))
                self.assertEqual(sum(int(row['messages']) for row in rows), 2)
                self.assertEqual({row['sender'] for row in rows}, {'@a','@b'})
                self.assertEqual({row['room_id'] for row in rows}, {'!one'})
            finally:
                subprocess.run(['pg_ctl','-D',str(data),'-m','immediate','-w','stop'], check=True, stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    unittest.main()
