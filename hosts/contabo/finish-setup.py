#!/usr/bin/env python3
"""Resume the executable parts of commissioning; never certify missing work."""
from datetime import datetime, timezone
from collections import Counter
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

STATE = Path('/var/lib/migration-queue/finish-setup')
OCC = '/run/current-system/sw/bin/nextcloud-occ'
CORE = ('matrix-synapse', 'nginx', 'mautrix-whatsapp', 'postgresql')


def command(args, *, capture=False, timeout=14400):
    return subprocess.run([str(x) for x in args], check=True, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          timeout=timeout).stdout


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def atomic(path, text):
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w') as fd:
        fd.write(text)
        fd.flush()
        os.fsync(fd.fileno())
    tmp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def parse_counts(output):
    result = {}
    for line in output.splitlines():
        key, sep, value = line.partition(': ')
        if sep and value.isdecimal():
            result[key] = int(value)
    required = ('Media files found', 'Sample', 'Exif inspected',
                'exif_batch_errors', 'exif_decode_errors')
    if any(key not in result for key in required):
        raise RuntimeError('Photo audit did not produce a complete count report')
    if (not result['Media files found'] or
            result['Sample'] != result['Media files found'] or
            result['Exif inspected'] != result['Sample'] or
            result['exif_batch_errors'] or result['exif_decode_errors']):
        raise RuntimeError('Photo audit did not inspect every media file successfully')
    return result


class Setup:
    def __init__(self):
        self.results = {}
        self.repair = load_script('mtime_repair', os.environ['CONTABO_MTIME_REPAIR_SCRIPT'])
        self.archive = load_script('archive_audit', os.environ['CONTABO_DISCORD_AUDIT_SCRIPT'])
        self.audit = load_script('photo_audit', os.environ['CONTABO_PHOTO_AUDIT_SCRIPT'])
        photo = load_script('photo_remediation', os.environ['CONTABO_PHOTO_REMEDIATION_SCRIPT'])
        self.remediation = photo.Remediation(self.audit, self.repair)

    def save(self):
        summary = ['CONTABO SETUP — current checks, not a claim of full completion',
                   'Updated: ' + datetime.now(timezone.utc).isoformat(), '']
        for name, result in self.results.items():
            summary.append(f"{result['status'].upper()}: {name}: {result['detail']}")
        unresolved = any(row['status'] != 'done' for row in self.results.values())
        summary += ['', 'SETUP INCOMPLETE: see remaining items above.' if unresolved else
                    'Automated checks passed; user-facing acceptance still required.',
                    'Run the same finish-setup.sh command again to recheck and resume.']
        atomic(STATE / 'status.json', json.dumps(self.results, indent=2) + '\n')
        atomic(STATE / 'summary.txt', '\n'.join(summary) + '\n')

    def record(self, name, status, detail):
        self.results[name] = {'status': status, 'detail': detail}
        self.save()
        print(f'{status.upper()}: {name}: {detail}', flush=True)

    def step(self, name, function):
        self.record(name, 'running', 'In progress')
        try:
            detail = function()
            self.record(name, 'done', detail)
            return True
        except Exception as exc:
            # Detailed commands can contain private paths. Full output stays in
            # the root-only log; the summary intentionally excludes their values.
            print(f'{name} exception: {type(exc).__name__}: {exc}', flush=True)
            self.record(name, 'blocked', f'{type(exc).__name__}; inspect the private run.log')
            return False

    def preflight(self):
        for unit in CORE:
            command(['systemctl', 'is-active', '--quiet', unit + '.service'])
        status = json.loads(command([OCC, 'status', '--output=json'], capture=True))
        if not status.get('installed') or status.get('maintenance') or status.get('needsDbUpgrade'):
            raise RuntimeError('Nextcloud requires maintenance or upgrade recovery')
        if self.archive.running_collectors():
            raise RuntimeError('Discord collector still running; leave its work undisturbed')
        if subprocess.run(['systemctl', 'is-active', '--quiet',
                           'discord-photos-queue.service']).returncode == 0:
            raise RuntimeError('Legacy migration queue is still running')
        for path in ('/var/lib/nextcloud', '/nix/store', str(STATE)):
            if shutil.disk_usage(path).free < 5 * 1024**3:
                raise RuntimeError('Less than 5 GiB free; no automatic deletion allowed')
        self.repair.check_root(True)
        return 'Core services and Nextcloud healthy; migration jobs idle; disk headroom checked'

    def backup(self):
        snapshot = self.repair.backup()
        # This reads repository metadata only. It is not an isolated restore.
        command(['/run/current-system/sw/bin/restic-contabo', 'check'])
        atomic(STATE / 'backup.json', json.dumps({'snapshot': snapshot}) + '\n')
        return 'Fresh R2 snapshot verified; repository metadata check passed'

    def photos(self):
        self.remediation.recover()
        output = command(['contabo-photo-audit', '--sample', '0'], capture=True)
        atomic(STATE / 'photo-audit.txt', output)
        parse_counts(output)
        plan = self.remediation.plan()
        atomic(STATE / 'photo-plan-before.json', json.dumps(plan, indent=2) + '\n')

        def fill_dates():
            pilot, kinds = [], set()
            for row in plan['metadata']:
                if row['file_type'] not in kinds:
                    pilot.append(row)
                    kinds.add(row['file_type'])
            self.remediation.apply_metadata(pilot)
            remaining = self.remediation.plan()['metadata']
            if len(remaining) != len(plan['metadata']) - len(pilot):
                raise RuntimeError('Missing-date pilot postcondition failed')
            self.remediation.apply_metadata(remaining)
            if self.remediation.plan()['metadata']:
                raise RuntimeError('Missing embedded capture dates remain')
            return 'Missing dates filled from verified Takeout metadata; decoded media verified; byte backups retained'

        # A failed/unsupported missing-date transform does not prevent Files
        # repairs for other independently verified photos.
        self.step('Missing capture dates', fill_dates)
        plan = self.remediation.plan()
        rows = plan['mtimes']
        # Each batch obtains its own fresh snapshot and writes durable undo data.
        # Recover interrupted writes/rescans first by scanning the same scope.
        self.repair.scoped_scan()
        if rows:
            for row in rows[:20]:
                self.remediation.validate_sidecars(row)
            self.repair.apply(rows, 20)
            remaining = self.remediation.plan()['mtimes']
            if len(remaining) != len(rows) - min(20, len(rows)):
                raise RuntimeError('Pilot mtime postcondition failed')
            for row in remaining:
                self.remediation.validate_sidecars(row)
            self.repair.apply(remaining, 0)
        final = self.remediation.plan()
        atomic(STATE / 'photo-exceptions.json', json.dumps(final, indent=2) + '\n')
        if final['mtimes']:
            raise RuntimeError('Eligible Files dates remain unrepaired')
        issues = Counter(row['reason'] for row in final['exceptions'])
        if final['metadata']:
            issues['missing_capture_date_pending'] += len(final['metadata'])
        self.record('Photo metadata exceptions', 'blocked' if issues else 'done',
                    json.dumps(dict(issues), sort_keys=True) if issues else 'No unresolved photo metadata exceptions')
        command([OCC, 'memories:index', '--user=wug', '--path=Photos/Google Photos', '--force'])
        return 'Eligible Files dates repaired; cache and Memories reindexed; conflicting/unresolved photos retained unchanged'

    def apps(self):
        # Preserve the current appstore deployment; no duplicate declarative
        # copies or app update/upgrade. Versions are inventoried for reproducibility.
        for app in ('calendar', 'contacts', 'tasks'):
            current = json.loads(command([OCC, 'app:list', '--output=json'], capture=True))
            if app in current.get('enabled', {}):
                continue
            if app in current.get('disabled', {}):
                command([OCC, 'app:enable', app])
            else:
                command([OCC, 'app:install', app])
            updated = json.loads(command([OCC, 'app:list', '--output=json'], capture=True))
            if app not in updated.get('enabled', {}):
                raise RuntimeError('Requested Nextcloud app is not enabled')
        current = json.loads(command([OCC, 'app:list', '--output=json'], capture=True))
        atomic(STATE / 'nextcloud-app-versions.json', json.dumps(current, indent=2) + '\n')
        return 'Calendar, Contacts and Tasks enabled using existing appstore; versions recorded'

    def discord(self):
        command(['contabo-discord-audit'])
        return 'Read-only archive inventory finished; this is not a historical Matrix import'

    def integrations(self):
        module = load_script('commission_integrations', os.environ['CONTABO_COMMISSION_SCRIPT'])
        detail = module.commission()
        self.backup()
        self.record('Integration account pairing', 'blocked', detail)
        return 'Slack, Google Messages and Matrimail services deployed; account acceptance separate'

    def mail(self):
        module = load_script('commission_integrations', os.environ['CONTABO_COMMISSION_SCRIPT'])
        self.record('Mail delivery acceptance', 'blocked', module.commission_mail())
        self.backup()
        return 'Mail service deployment and mailbox provisioning completed; delivery acceptance separate'

    def discord_native(self):
        module = load_script('commission_integrations', os.environ['CONTABO_COMMISSION_SCRIPT'])
        self.record('Discord history and live cutover', 'blocked', module.commission_discord())
        self.backup()
        return 'Discord service deployed; import/pairing/coverage state is recorded separately'

    def run(self):
        # Reset stale RUNNING records after interruption; recheck actual state.
        self.record('Overall commissioning', 'blocked', 'Waiting for all deployment and acceptance checks')
        if not self.step('Preflight', self.preflight):
            return 2
        backed_up = self.step('Offsite backup', self.backup)
        if backed_up:
            self.step('Photo Files dates', self.photos)
            self.step('Nextcloud apps', self.apps)
            if self.step('Messaging service deployment', self.integrations):
                self.step('Discord native deployment', self.discord_native)
                self.step('Mail service deployment', self.mail)
        else:
            self.record('Photo Files dates', 'blocked', 'Fresh backup prerequisite failed')
            self.record('Nextcloud apps', 'blocked', 'Fresh backup prerequisite failed')
        self.step('Discord archive inventory', self.discord)
        # These are implementation/acceptance gaps, not consent prompts. Do not
        # replace them with forgeable completion markers or assume that a
        # running bridge has authenticated or passed send/receive tests.
        for name, detail in (
            ('Isolated recovery',
             'Repository check passed only if recorded above; isolated application restore still needed'),
            ('Client acceptance',
             'Verify photo timeline/map, phone upload, DAV sync, WhatsApp and encryption recovery in clients'),
            ('Declarative app migration',
             'Google apps retain stateful installation; audited migration to pinned Nix apps remains'),
        ):
            self.record(name, 'blocked', detail)
        return 2


def main():
    if os.geteuid() != 0 or os.uname().nodename.split('.')[0] != 'contabo':
        raise RuntimeError('Run as root on Contabo')
    os.umask(0o077)
    STATE.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (STATE / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return Setup().run()


if __name__ == '__main__':
    sys.exit(main())
