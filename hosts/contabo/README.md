# Contabo host

This directory is an **independent flake in the same Git repository** as the
desktop configuration. That is intentional: the desktop follows nixos-unstable,
while this already-running server was installed with NixOS 26.05. The two
machines must not silently switch package channels or bootloaders.

- Desktop: `sudo nixos-rebuild switch --flake /etc/nixos#nixos`
- VPS: `sudo nixos-rebuild switch --flake /etc/nixos/hosts/contabo#contabo`

The Contabo config includes static IPv4/IPv6 networking, matching the NIC's MAC
address, BIOS GRUB, existing SSH public keys, the `wug` sudo account, a small
Fish/Helix environment, and Nextcloud.

## First migration (on Contabo, **no rebuild yet**)

1. **Back up the currently working live config** before replacing `/etc/nixos`.
   Keep a recovery console available.
2. Clone this repository to a new staging directory, such as
   `/etc/nixos-new`, without overwriting the existing `/etc/nixos`.
3. Copy the *existing* `/etc/nixos/flake.lock` to
   `/etc/nixos-new/hosts/contabo/flake.lock`. Both server flakes have the
   same `nixpkgs` and `disko` inputs. Retain this lock file in Git when
   updating from the server.
4. Compare `/etc/nixos/nextcloud.nix` against
   `/etc/nixos-new/hosts/contabo/nextcloud.nix` and **retain any changes
   already working on the VPS**. In particular, preserve newer Memories or
   Nextcloud settings. The file in Git is a baseline, not a verified export
   of the live VPS.
5. Ensure `/var/lib/secrets/nextcloud-admin` remains present; it is
   intentionally not in Git. Never commit plaintext secrets or tokens.
6. Git flakes ignore untracked files. Stage the copied server `flake.lock`
   in the staged checkout before evaluation (e.g. `git add -N
   hosts/contabo/flake.lock`), then run:

   ```bash
   sudo nix flake check /etc/nixos-new/hosts/contabo
   sudo nixos-rebuild build --flake /etc/nixos-new/hosts/contabo#contabo
   ```

   **Do not switch** until both pass and the effective network/boot/SSH
   settings have been compared to the current running system.

7. Only then arrange the checked-out repository at `/etc/nixos`, and
   deploy with `sudo nixos-rebuild switch --flake
   /etc/nixos/hosts/contabo#contabo`. Confirm SSH access in a second
   session before closing the first.

The repo contains no user data. Nextcloud databases/files, authentication
tokens, private keys, and Cloudflare credentials remain on the server or in
separate encrypted backups.

## Maintenance

Edit the host modules, then use:

```bash
sudo nix flake check /etc/nixos/hosts/contabo
sudo nixos-rebuild build --flake /etc/nixos/hosts/contabo#contabo
sudo nixos-rebuild switch --flake /etc/nixos/hosts/contabo#contabo
```

No `nixos-anywhere` or `disko` formatting command is needed for ordinary
updates. The running system already has partitions and Nextcloud data.
