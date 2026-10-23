# Contabo operations and reproducibility

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
The archive and live-bridge mapping databases serve different purposes.

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
