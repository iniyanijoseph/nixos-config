# Contabo host

**Current operational guide:** [OPERATIONS.md](./OPERATIONS.md). It distinguishes
permanent NixOS services, one-time migrations and private state. The native
Discord historical importer has not yet been implemented or deployed.

This directory is an **independent flake in the same Git repository** as the
desktop configuration. That is intentional: the desktop follows nixos-unstable,
while this already-running server was installed with NixOS 26.05. The two
machines must not silently switch package channels or bootloaders.

- Desktop: `sudo nixos-rebuild switch --flake /etc/nixos#nixos`
- VPS: `sudo nixos-rebuild switch --flake /etc/nixos/hosts/contabo#contabo`

The Contabo config includes static IPv4/IPv6 networking, matching the NIC's MAC
address, BIOS GRUB, existing SSH public keys, the `wug` sudo account, a small
Fish/Helix environment, and Nextcloud.

## Deployment

The initial migration to GitHub-managed NixOS is complete. The original
configuration was saved as `/etc/nixos-bootstrap-backup` on the VPS; keep it
until a clean reboot and SSH reconnection have been tested.

On Contabo:

```bash
cd /etc/nixos
sudo git pull --ff-only
sudo nix flake check ./hosts/contabo
sudo nixos-rebuild switch --flake ./hosts/contabo#contabo
```

The NixOS version of this host is locked in `hosts/contabo/flake.lock`,
separate from the desktop's `flake.lock`. Commit deliberate changes to either
lock file. Never add passwords, tokens, or the Nextcloud data directory to Git.

## Nextcloud Memories smoke test

The NixOS configuration supplies ExifTool, Perl and FFmpeg/FFprobe using
absolute Nix store paths. It limits generated image previews to 2048 pixels;
original photos remain unchanged.

After deployment:

```bash
sudo nextcloud-occ status
sudo nextcloud-occ config:system:get memories.exiftool
sudo nextcloud-occ config:system:get memories.vod.ffmpeg
sudo nextcloud-occ config:system:get preview_ffprobe_path
systemctl list-timers 'nextcloud*' --all
sudo nextcloud-occ memories:index
```

In Nextcloud's **Administration settings → Memories**, confirm ExifTool
and video preview tools now pass their checks. For ordinary uploads, Memories
indexes via Nextcloud background jobs; do not add a second periodic full-index
job. For a small test library, the initial `memories:index` is sufficient.
Test a photo with GPS EXIF and a small video before bulk migration.

The Preview Generator app depends on Nextcloud cron mode for automatic jobs.
If it is not set, run `sudo nextcloud-occ background:cron`; for an initial
backlog, optionally run `sudo nextcloud-occ preview:pre-generate`.

**Encrypted backups are enabled in the NixOS configuration**, but they are
not operational until the R2 credentials and Restic password exist locally,
the VPS is rebuilt, and a backup plus restore test succeeds. Follow
[the Cloudflare R2 setup](./BACKUPS.md) before rebuilding.

## Maintenance

Edit the host modules, then use:

```bash
sudo nix flake check /etc/nixos/hosts/contabo
sudo nixos-rebuild build --flake /etc/nixos/hosts/contabo#contabo
sudo nixos-rebuild switch --flake /etc/nixos/hosts/contabo#contabo
```

No `nixos-anywhere` or `disko` formatting command is needed for ordinary
updates. The running system already has partitions and Nextcloud data.

## Matrix Synapse + Cinny

The homeserver and web client are described in [`matrix.nix`](./matrix.nix).
Follow [`MATRIX.md`](./MATRIX.md) to provision the DNS records, create the
root-only registration secret, deploy, verify federation and register `@me`.
The existing Restic job includes `/var/lib/matrix-synapse` and PostgreSQL.

## Optional Matrix migration monitoring (staged, disabled)

`monitoring.nix` packages the private Matrix status listener and 20-minute
migration reporter using the pinned Contabo flake. It is imported but
`contabo.matrixMonitoring.enable = false;` until a controlled cutover replaces
the existing transient systemd units. See [OPERATIONS.md](./OPERATIONS.md).
