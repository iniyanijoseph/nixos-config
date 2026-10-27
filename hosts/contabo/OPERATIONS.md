# Contabo operations and reproducibility

## Integration implementation (draft; not full commissioning)

The integration commissioner now generates the Slack, Google Messages and
Matrimail configurations and registrations from their actual CLI templates.
Private files remain under each service's `/var/lib` directory; existing
credentials and encryption state are preserved. It builds an extended Contabo
configuration with `contabo.integrations.enable = true`, switches the system
profile, checks the services and rolls back the previous generation on failure.
This phase **does switch NixOS**. The earlier photo-only runner did not.
Keep using the commissioner for subsequent integration deployments: switching
the baseline flake with the optional flags false disables those integrations.
The selected generation persists across reboot.

Pairing and actual send/receive checks remain separate from deployment:
Google Messages requires phone approval, Slack requires each workspace login,
and Matrimail requires its account login flow. The report gives bot addresses
and marks these unverified; it does not claim account authentication from
`systemctl is-active`. Existing WhatsApp pairing is preserved.

The optional Stalwart phase requires DNS-only `mail.iniyanjoseph.com` pointing
to this VPS. It retains or generates root-only administrator/mailbox secrets,
activates the mail configuration and uses the version-0.15 principal API to
provision the domain and mailbox. It does not change MX, forwarding or provider
DNS. External delivery, PTR, SPF/DKIM/DMARC and standard-client acceptance
remain required. No email is sent automatically by commissioning.

The Discord package `contabo-discord-native` is an **experimental, disabled**
fork. It streams source messages oldest first through the pinned bridge's
converter and mapping layer, uses stable part transaction IDs and reads the
SQLite source in a read-only transaction. It fails closed on missing mappings.
Crash-resume, initial-room selection, media completeness and cutover still need
integration verification. Do not enable it for the real archive yet. The old
Discord bridge requires legacy libolm; its insecure-package exception is scoped
to this experimental build, not globally enabled. No production Discord
service is started by this draft.

## Single setup entry point

After fetching current `main`, run:

```fish
sudo bash /etc/nixos/hosts/contabo/finish-setup.sh
```

This **applies changes**, unlike `setup-phase1.fish`. It starts a pinned
systemd worker which survives SSH disconnects. Run
the same command again after resolving a failure; it rechecks actual state
rather than trusting old success checkpoints. It never switches NixOS.

Implemented automation checks services, disk space and idle migration jobs,
verifies a fresh R2 snapshot, audits all photos, repairs eligible Files mtimes
in a journaled 20-file pilot followed by the remaining eligible files,
rescans the scoped cache, enables/installs Calendar, Contacts and Tasks using
the existing stateful app store, and inventories the Discord archive.
Enabled apps are not upgraded. Existing valid dates, GPS, Takeout and duplicate
quarantine are preserved. Photo exceptions are handled per file: conflicting
dates and uncertain pairings are skipped without blocking unrelated repairs.
Missing capture dates in supported formats can be filled from verified Takeout
timestamps, with the original media retained for byte-exact rollback.

The per-file planner accepts agreeing exact sidecars or a unique exact Takeout
`title` filename match in the same directory. It does not guess truncated names
or choose between disagreeing capture metadata. JPEG, PNG, TIFF and WebP get
EXIF DateTimeOriginal with an explicit UTC offset; MP4/MOV/M4V get QuickTime
CreateDate and Keys CreationDate. Valid pre-existing dates are not overwritten.
Before replacement, the runner verifies the written date, unchanged GPS and
identical decoded image/video and audio stream hashes using FFmpeg. It also
checks that the source and sidecars did not change during verification.

Each metadata batch obtains a fresh R2 snapshot and retains the original inode
and bytes in `/var/lib/migration-queue/photo-metadata-journals/`. A pilot covers
each detected format before the remaining missing dates. A failed or interrupted
batch is rolled back before a new plan; source files changed outside the repair
are never silently overwritten. Disk space is checked before keeping originals.
The scoped Files cache and Memories index are refreshed after repair.

Private before/after plans, including the precise files requiring review, are
in `finish-setup/photo-plan-before.json` and `finish-setup/photo-exceptions.json`.
These can include filenames, capture times and GPS; do not publish them. A
read-only aggregate plan is available with `sudo nix run
/etc/nixos/hosts/contabo#contabo-photo-remediation`.

For a deliberate metadata rollback, use the exact journal directory shown in
the private plan/log; roll back any later Files-mtime journal first if needed:

```fish
sudo nix run /etc/nixos/hosts/contabo#contabo-photo-remediation -- \
  --rollback /var/lib/migration-queue/photo-metadata-journals/EXACT-JOURNAL \
  --confirm ROLLBACK-PHOTO-METADATA
```

Do not invent a journal name or delete its original-media files. The old
whole-library audit is retained for comparison; its ambiguous/missing-sidecar
counts do not distinguish the verified per-file pairing rules above.

**Every phase is not yet executable.** The native Discord importer, bridge
provisioning/pairing, Stalwart/Matrimail commissioning, declarative app migration,
isolated recovery and client acceptance remain listed as incomplete. The
worker exits nonzero while these remain; a failed unit can mean an unfinished
implementation/acceptance item. Read the summary to identify what remains.

```fish
sudo bash /etc/nixos/hosts/contabo/finish-setup.sh --status
```

The root-only summary, JSON status, log, audit and version inventory live in
`/var/lib/migration-queue/finish-setup/` and are covered by the next migration
state backup. Detailed logs may contain private paths; do not publish them.
Closing the viewer leaves the worker running. To prevent future boot runs
after retiring setup, remove only its boot-resume marker:
`sudo rm -f /var/lib/migration-queue/finish-setup/resume-on-boot`.
This does not interrupt a running repair or remove logs, journals or data.

On NixOS, the launcher installs its runtime unit in `/run/systemd/system`.
It does not write to the read-only `/etc/systemd/system` or call `systemctl
enable`. Until `finish-setup.nix` has been deployed by an ordinary NixOS
switch, a reboot clears the runtime unit: run the same launcher to resume.
Once deployed, the declarative unit resumes a previously started run at
boot. Before setup has ever been launched, its conditions skip the service.
The launcher reports which mode is currently available. Do not reboot during
a repair simply to test this; an interrupted repair may need a scoped rescan.

The first run builds its pinned closure before starting the worker. Keep SSH
connected until it prints that setup is running under systemd.

**One-command read-only inventory:** `sudo /run/current-system/sw/bin/fish /etc/nixos/hosts/contabo/observe.fish` (after pulling the reviewed Git commit). It prints sanitized state only; no secret values or private message bodies. See [SETUP-PLAN.md](./SETUP-PLAN.md) for the full service target and phased acceptance criteria.

This is the **current** operational index for the NixOS 26.05 VPS.
The server flake is `/etc/nixos/hosts/contabo#contabo`, distinct from the
desktop flake. Run these commands **on the VPS** unless explicitly stated.
Cloning the repository reproduces code, not account sessions or user data.

## Persistent services vs. migrations

| Component | Definition | Persistent state | Deployment |
| --- | --- | --- | --- |
| Nextcloud | `nextcloud.nix` | `/var/lib/nextcloud`, PostgreSQL | Declarative |
| Synapse/Cinny | `matrix.nix` | `/var/lib/matrix-synapse`, PostgreSQL | Declarative |
| WhatsApp | `whatsapp.nix` | `/var/lib/mautrix-whatsapp`, private key | Declarative |
| R2 backup | `backups.nix` | R2 repository; `/var/lib/secrets` | Declarative |
| Matrix alerts | `monitoring.nix` | alert credential and sync cursor | Opt-in, currently disabled |
| Discord archive | `discord-archive/` | `/var/lib/discord-archive` | One-time manual collection |
| Takeout migration | `migration-queue.py` | `/var/lib/migration-queue` | One-time; **currently stopped** |
| Live Discord | `discord.nix` | planned `/var/lib/mautrix-discord` | **Disabled, not ready** |

The Discord archive is *not* currently Matrix history. No historic importer,
live Discord bridge, or retirement command is deployed by this change.

## Full-setup Phase 1: Google Photos and Nextcloud apps

The current Google Takeout migration has completed its one-shot command,
but a command exit checkpoint **does not certify correct dates or GPS**.
One verified January 2026 photo had correct embedded EXIF despite an
October 2026 upload date shown in the Nextcloud Files view. Do not rewrite
correct embedded camera metadata to "fix" the Files mtime without measuring.

The canonical read-only start is:

```fish
sudo /run/current-system/sw/bin/fish -n /etc/nixos/hosts/contabo/setup-phase1.fish
and sudo /run/current-system/sw/bin/fish /etc/nixos/hosts/contabo/setup-phase1.fish
```

This checks core services, Nextcloud app status (Calendar, Contacts, Tasks,
Memories, etc.), and a deterministic 500-file comparison of Google sidecar
`photoTakenTime` vs EXIF date, EXIF GPS and filesystem mtime. It
redacts filenames/coordinates and cannot change any photo. Re-run
`contabo-photo-audit --sample 0` later for the full library after initial
classification; this scans every media file and is correspondingly slower.

Repair pathways are **not interchangeable**:

- Correct EXIF and wrong Files timestamp: fix file mtime from the verified
  capture time, then rescan Nextcloud's file cache for changed files.
- Wrong/missing EXIF with good Google sidecar: import the specific capture
  time/GPS into the appropriate image or video metadata format **after
  verified backup**, then force a scoped Memories reindex.
- EXIF vs sidecar shifted only by timezone: preserve the camera's original
  local clock and offset unless an explicit provenance check proves it wrong.
- Sidecar ambiguous or missing: inventory and resolve conservatively; never
  guess attachments or pair unrelated files.
- Correct source metadata but wrong Memories timeline: diagnose the Memories
  index/database and force a scoped reindex before any file rewrite.

`contabo.googleSuite.enable` is separately staged but OFF until inspecting
the live app list to avoid Nix/store-appstore collision. Existing Memories
remains enabled through the stateful Nextcloud app store.

### Safe Files-date repair (explicit, never automatic)

The first 500-file audit found 490 uniquely paired Takeout capture dates,
all 490 different from filesystem mtimes, and 334 matching GPS fields.
Existing EXIF should not be mass rewritten based on that result.

Run the **read-only** full-library comparison first:

```fish
cd /etc/nixos
sudo nix run ./hosts/contabo#contabo-photo-audit -- --sample 0
sudo nix run ./hosts/contabo#contabo-photo-mtime-repair -- --limit 20
```

The repair program changes nothing unless explicitly given `--apply` and
a confirmation phrase. To do a 20-file pilot (requires a fresh R2 backup,
durable pre-change journal and a scoped Nextcloud Files rescan):

```fish
sudo nix run ./hosts/contabo#contabo-photo-mtime-repair -- \
  --apply --limit 20 --confirm APPLY-PHOTO-MTIMES
```

If Nextcloud displays the expected dates after the pilot and the full audit
shows no unexpected metadata conflicts, perform the remaining eligible
files with `--limit 0`. This triggers **another fresh backup**, and
does not edit EXIF/GPS/media bytes, move folders, or delete duplicates.

Private rollback journals are saved in
`/var/lib/migration-queue/photo-mtime-journals/<timestamp>-<id>/`. If a
rescan fails, keep the journal and redo the scoped rescan or roll back:

```fish
sudo nix run ./hosts/contabo#contabo-photo-mtime-repair -- \
  --rollback /var/lib/migration-queue/photo-mtime-journals/EXACT-JOURNAL-DIR \
  --confirm ROLLBACK-PHOTO-MTIMES
```

Never guess the journal directory; use the exact one printed by the repair.
The journal contains private relative paths and must not be published.
If the **Memories** timeline is wrong despite valid embedded dates, a Files
mtime repair by itself will not correct it: inspect the Memories index and
camera timezone handling. Missing EXIF dates and ambiguous Google sidecars
require separate conservative treatment after classification.

## Focused Discord archive inventory and monitoring opt-out

The standard `observe.fish` report relies on the optional `sqlite3`
binary and a narrow process matcher. A missing binary or zero processes in
that summary **does not establish archive completion**. For a more reliable
sanitized read-only inspection, execute this Nix-packaged Python tool:

```fish
cd /etc/nixos
sudo nix run ./hosts/contabo#contabo-discord-audit

# Optional deeper, read-only scan of existing message JSON:
# counts references to attachments, replies, edited messages, embeds,
# reactions and stickers without emitting private content.
sudo nix run ./hosts/contabo#contabo-discord-audit -- --deep
```

It uses the pinned Contabo Python, opens the SQLite database strictly in
read-only mode (including WAL), scopes known conversations to the configured
Discord guild and DMs, and reports aggregate completion/errors only. It
never authenticates to Discord or imports messages into Matrix. Even the
deep scan **does not download attachments** or establish their recoverability.
The last collector reported an HTTP 403 for active-thread discovery. Do not
try to bypass endpoint access restrictions or resume a personal-token
self-bot: the official Discord bot API is the supported automation route.

If private Matrix monitoring is no longer wanted, after verifying that only
the old transient listener/timer are active, this single-purpose script stops
those two **only** and leaves Synapse, Nextcloud, WhatsApp and Discord alone:

```fish
sudo /run/current-system/sw/bin/fish -n /etc/nixos/hosts/contabo/stop-transient-monitoring.fish
and sudo /run/current-system/sw/bin/fish /etc/nixos/hosts/contabo/stop-transient-monitoring.fish
```

It fails closed on unexpected unit identity, nontransient services, or
unhealthy core services. Leave `contabo.matrixMonitoring.enable = false` to
avoid restarting notifications on reboot.

## Read-only checks before any change

```fish
hostname
git -C /etc/nixos status --short
git -C /etc/nixos log -1 --oneline
systemctl is-active matrix-synapse nginx mautrix-whatsapp
env TERM=xterm-256color SYSTEMD_PAGER=cat systemctl list-timers --all --no-pager
sudo restic-contabo snapshots
```

Check every output. On a different host, dirty checkout, or missing backup,
stop and investigate rather than applying an unrelated command.

## Review and deploy the NixOS configuration

**This branch only stages optional monitoring and future Discord backup
coverage**; it does not activate or restart a service. Do not enable the
optional module until the migration jobs are quiescent.

```fish
cd /etc/nixos
git status --short
sudo nix flake check ./hosts/contabo
sudo nixos-rebuild build --flake ./hosts/contabo#contabo
```

`build` prepares a generation but does not activate it. To switch **after**
reviewing the difference and confirming access/backup/reboot recovery:

```fish
sudo nixos-rebuild switch --flake ./hosts/contabo#contabo
```

Do not use `disko` formatting or reinstall commands for routine updates.

## Make Matrix monitoring persistent (future controlled cutover)

`contabo.matrixMonitoring.enable` defaults to `false` in
`configuration.nix`. Enabling it provisions Nix-built Python scripts,
`matrix-command-listener.service`, `matrix-periodic-status.service`, and
`matrix-periodic-status.timer`. The 20-minute timer is persistent across
reboots and sends no messages after its final checkpoint.

**Do not run the declarative and transient listeners simultaneously.**
Before enabling, use these *read-only* checks:

```fish
env TERM=xterm-256color systemctl show matrix-command-listener.service -p ActiveState -p Transient -p ExecStart --no-pager
env TERM=xterm-256color systemctl show matrix-periodic-status.timer -p ActiveState -p Transient --no-pager
sudo test -s /var/lib/secrets/matrix-alerts.json; and echo 'Secret present'
```

Validate the current transient unit IDs and executables first. Then perform
a deliberately reviewed cutover, with the new module enabled in Git: stop
the **two verified transient monitoring units only**, build the new generation,
switch, and verify one `!status` reply and one timer message. Never touch
`matrix-synapse.service`, `mautrix-whatsapp.service`, or the independent
Discord collector as part of monitoring cutover.

These scripts currently require root access to an existing private alert
token and read-only archive/backup information; sandboxing limits writes to
the migration state folder. A future narrower service account requires a
separate credentials and read-permission design.

## Backup and recovery

The Restic configuration includes Nextcloud, Synapse, WhatsApp, the active
Discord **archive** and migration state, private secrets, TLS/SSH keys and
a PostgreSQL logical dump. The future live Discord bridge directory is
included conditionally **when `services.mautrix-discord.enable = true`**.
The archive and live-bridge mapping databases serve different purposes. The legacy migration queue has been changed to **never perform photo quarantine cleanup or shell-based offline service preflights automatically**.

```fish
sudo systemctl start restic-backups-contabo.service
sudo restic-contabo snapshots
sudo restic-contabo check
```

Restic success alone does **not** establish a consistent restoration of
Synapse media, the database, Matrix signing keys, encryption keys and
bridge mappings. Restore to an **isolated** instance and verify before
retiring the archive or original photo export.

Do not put secrets in Git or the Nix store. Recover them from separately
protected backups. Do not rotate a Synapse server signing key accidentally.
The Matrix `server_name` must remain stable.

## Migration completion is not application correctness

- Takeout metadata and indexing checkpoints do not prove that original
  dates/GPS appear correctly in the Memories client.
- Keep the photo quarantine until a manual metadata audit, successful
  post-audit backup, and a separately approved cleanup.
- A Discord archive completion checkpoint does not mean old Discord
  messages exist as Matrix events. A native importer, per-room mapping,
  attachment audit, cutover and restore test are still required.
- Discord archive collection is incomplete while active-thread discovery
  is blocked. Do not silently interpret this as completeness.
- Never remove SQLite or its media sources until every recoverable
  message has a verified Matrix counterpart and a restore has succeeded.

## Future one-command operations (not yet implemented)

A small Nix-built `contaboctl` may eventually expose `doctor`,
`backup verify`, `discord import --dry-run`, `discord verify` and
`discord cutover`. These are a **design**, not commands to run now.

See `MATRIX.md`, `BACKUPS.md` and the service modules for setup details.
Older `DISCORD.md` instructions refer to a retired bridge configuration
and are **not** a current deployment runbook.
