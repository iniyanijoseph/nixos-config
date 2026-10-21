# NixOS configurations

This repository contains the **desktop** and the **Contabo VPS**. They use
separate flakes in one repository to preserve their independent NixOS versions.

| Machine | Hostname | Flake | Configuration |
| --- | --- | --- | --- |
| ThinkPad desktop | `nixos` | `/etc/nixos` | `#nixos` |
| Contabo VPS | `contabo` | `/etc/nixos/hosts/contabo` | `#contabo` |

The root `flake.nix`, `flake.lock`, and existing desktop/Home Manager
configuration are unchanged. Contabo is configured under [hosts/contabo](hosts/contabo/README.md)
and pinned to NixOS 26.05.

The server is already deployed separately. **Adding files to this repo does
not update the VPS**. Reconcile the live server files and its working
`flake.lock` before rebuilding it from this repository.

Keep passwords, tokens, encryption keys, and service data out of Git.
