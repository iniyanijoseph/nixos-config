#!/usr/bin/env python3
"""Resume the executable parts of commissioning; never certify missing work."""
from datetime import datetime, timezone
from collections import Counter
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import yaml
import shutil
import sqlite3
import subprocess
import sys

STATE = Path('/var/lib/migration-queue/finish-setup')
OCC = '/run/current-system/sw/bin/nextcloud-occ'
DISCORD_NATIVE = Path('/var/lib/mautrix-discord-native')
MATRIMAIL_HOME = Path('/var/lib/matrimail')
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
        self.photos_deferred = True
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
        return 'Core services and Nextcloud healthy; migration jobs idle; disk headroom checked'

    def backup(self):
        snapshot = self.repair.backup()
        # This reads repository metadata only. It is not an isolated restore.
        command(['/run/current-system/sw/bin/restic-contabo', 'check'])
        atomic(STATE / 'backup.json', json.dumps({'snapshot': snapshot}) + '\n')
        return 'Fresh R2 snapshot verified; repository metadata check passed'

    def photos(self):
        self.repair.check_root(True)
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
        directory = DISCORD_NATIVE
        snapshot, mapping = directory / 'archive.sqlite', directory / 'bridge.db'
        # Once the user has native historical state, ordinary commissioning
        # must not repeatedly POST the archive, re-pair, or restart its bridge.
        # The archive and native mappings can be checked without a login.
        if snapshot.is_file() and mapping.is_file():
            with sqlite3.connect('file:' + str(snapshot) + '?mode=ro', uri=True) as source:
                channels = [row[0] for row in source.execute(
                    "SELECT id FROM channels WHERE kind IN ('dms','guild:804408079940583475')")]
            owner = None
            if module.discord_pilot_verified():
                owner = json.loads((module.STATE / 'discord-pilot-verified.json').read_text())['receiver']
            expected, mapped = module.discord_coverage(snapshot, mapping, channels, owner)
            verified = bool(owner and expected and expected == mapped)
            self.record('Discord historical mapping coverage',
                        'done' if verified else 'blocked',
                        f'{mapped}/{expected} selected-scope historical message mappings; '
                        + ('receiver verified' if owner else 'account receiver not independently verified')
                        + '; live session and media parity are separate checks')
            return 'Existing Discord native import preserved; no repeated historical replay or bridge re-pairing'
        self.record('Discord history and live cutover', 'blocked', module.commission_discord())
        self.backup()
        return 'Discord service provisioned; import and live login require separate acceptance'

    def ensure_matrimail_contact_routing(self):
        """Restore and verify contact routing after all mail-service switches.

        The initial commissioning applies this overlay before its NixOS
        switches, but a later switch may leave a different live config.
        Reapply only this bridge's non-secret settings, preserving tokens,
        encrypted state and existing email accounts.
        """
        module = load_script('commission_integrations',
                             os.environ['CONTABO_COMMISSION_SCRIPT'])
        changed, registration_digest = module.enable_matrimail_contact_rooms(MATRIMAIL_HOME)
        config = yaml.safe_load((MATRIMAIL_HOME / 'config.yaml').read_text())
        if config.get('network', {}).get('contact_rooms') is not True:
            raise RuntimeError('Matrimail contact routing is disabled after applying pinned settings')
        # An appservice namespace update requires Synapse reload. The
        # earlier commission() step must handle it before any bridge restart.
        marker = MATRIMAIL_HOME / '.contact-registration-loaded.json'
        try:
            loaded = json.loads(marker.read_text()).get('sha256')
        except (OSError, ValueError):
            loaded = None
        if loaded != registration_digest:
            raise RuntimeError('Matrimail registration changed after Synapse reload; rerun messaging commissioning')
        if changed:
            command(['systemctl', 'restart', 'matrimail.service'])
            command(['systemctl', 'is-active', '--quiet', 'matrimail.service'])
            return 'Re-enabled Matrimail contact routing and restarted only Matrimail; historical replay is asynchronous'
        return 'Matrimail contact routing enabled; existing account and Matrix room state preserved'

    def email_consolidation(self):
        """Require verifiable contact-room history before automatic photo work.

        This read-only audit cannot prove content or source IMAP completeness,
        but prevents a silent, unfinished Matrimail replay from being treated
        as completed simply because the service was restarted.
        """
        script = os.environ.get('CONTABO_ADMIN_SCRIPT')
        if not script:
            raise RuntimeError('Private Matrimail audit script is not configured')
        admin = load_script('contabo_mail_admin', script)
        report = admin.mail_consolidation_status()
        atomic(STATE / 'mail-consolidation.json', json.dumps(report, indent=2) + '\n')
        if not report.get('contact_routing_enabled'):
            raise RuntimeError('Contact-based email routing is not enabled')
        if not report.get('bridge_logins'):
            raise RuntimeError('No saved Matrimail account login for historical import')
        if not report.get('contact_rooms') or not report.get('contact_message_parts'):
            raise RuntimeError('No populated contact-based email rooms; consolidation is not confirmed')
        old = report['legacy_rooms']
        if old:
            if report['legacy_message_parts'] == 0:
                raise RuntimeError('Legacy email rooms exist but have no auditable native message mappings')
            if report['legacy_parts_with_contact_mappings'] < report['legacy_message_parts']:
                raise RuntimeError('Matrimail history replay is incomplete; preserve old email rooms')
            if report['archived_legacy_rooms'] < old:
                raise RuntimeError('Matrimail contact rooms exist but historical room retirement is incomplete')
        return (f"Contact-room audit passed: {report['legacy_parts_with_contact_mappings']}/"
                f"{report['legacy_message_parts']} legacy parts mapped; "
                f"{report['archived_legacy_rooms']}/{old} legacy rooms archived. "
                "Email sending and attachment parity need separate acceptance.")

    def after_email(self):
        """Timer retry: resume photo work once mail history is reconciled.

        The main runner and this follow-up share the same worker lock, so a
        new NixOS switch or interactive launcher never overlaps remediation.
        """
        if (STATE / 'photo-after-email-complete').exists():
            return 0
        if not self.step('Post-mail preflight', self.preflight):
            return 2
        if not self.step('Matrimail contact routing', self.ensure_matrimail_contact_routing):
            self.record('Photo Files dates', 'deferred',
                        'Waiting for valid Matrimail contact routing; Discord login is not the blocker')
            return 2
        if not self.step('Email consolidation', self.email_consolidation):
            self.record('Photo Files dates', 'deferred',
                        'Waiting for verified email contact-room mappings; Discord login is not the blocker')
            return 2
        if not self.step('Post-mail offsite backup', self.backup):
            return 2
        photos_ok = self.step('Photo Files dates', self.photos)
        apps_ok = self.step('Nextcloud apps', self.apps)
        if photos_ok and apps_ok:
            atomic(STATE / 'photo-after-email-complete', 'Photo stage and Nextcloud apps verified after email audit\n')
        return 0 if photos_ok and apps_ok else 2

    def run(self):
        # Reset stale RUNNING records after interruption; recheck actual state.
        self.record('Overall commissioning', 'blocked', 'Waiting for all deployment and acceptance checks')
        if not self.step('Preflight', self.preflight):
            return 2
        backed_up = self.step('Offsite backup', self.backup)
        if backed_up:
            # Email reconstruction has priority; avoid a premature Discord
            # reconfiguration or expensive archive walk before the mail audit.
            messaging_ok = self.step('Messaging service deployment', self.integrations)
            if messaging_ok:
                mail_ok = self.step('Mail service deployment', self.mail)
                routing_ok = (self.step('Matrimail contact routing', self.ensure_matrimail_contact_routing)
                              if mail_ok else False)
                email_ok = (self.step('Email consolidation', self.email_consolidation)
                            if routing_ok else False)
                if not mail_ok or not routing_ok:
                    self.record('Email consolidation', 'blocked',
                                'Mail deployment or Matrimail routing did not complete')
            else:
                email_ok = False
                self.record('Email consolidation', 'blocked', 'Messaging deployment did not complete')
            if email_ok:
                photos_ok = self.step('Photo Files dates', self.photos)
                apps_ok = self.step('Nextcloud apps', self.apps)
                if photos_ok and apps_ok:
                    atomic(STATE / 'photo-after-email-complete', 'Photo stage and Nextcloud apps verified after email audit\n')
            else:
                self.record('Photo Files dates', 'deferred',
                            'Waiting for email-room consolidation; Discord authentication does not block photos')
                self.record('Nextcloud apps', 'deferred',
                            'Scheduled after email consolidation and photo work')
            if ((DISCORD_NATIVE / 'archive.sqlite').is_file()
                    and (DISCORD_NATIVE / 'bridge.db').is_file()):
                self.step('Discord native deployment', self.discord_native)
            elif email_ok:
                self.step('Discord native deployment', self.discord_native)
            else:
                self.record('Discord native deployment', 'deferred',
                            'Existing email replay takes priority over new Discord provisioning')
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
             'Verify Discord send/receive and replies, Slack, SMS/RCS, mail, WhatsApp and encryption recovery; photos are lower priority'),
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
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # An already-running commissioning worker owns the host. The
            # timer retries later; never overlap private data migrations.
            # A new NixOS generation can start the boot-resume unit while
            # this very worker is switching that generation. Treat the
            # duplicate invocation as a no-op, not an unhandled traceback.
            # The primary worker retains the lock and writes real results.
            print('Another Contabo commissioning worker is already active; duplicate start skipped', flush=True)
            return 0
        if len(sys.argv) > 1 and sys.argv[1] == '--after-email':
            return Setup().after_email()
        if len(sys.argv) > 1:
            raise SystemExit('Usage: contabo-finish-setup [--after-email]')
        return Setup().run()


if __name__ == '__main__':
    sys.exit(main())
