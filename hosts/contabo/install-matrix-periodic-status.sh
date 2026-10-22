#!/usr/bin/env bash
# Install a root-owned transient timer. No NixOS switch or collector restart.
set -euo pipefail
cd /etc/nixos
/usr/bin/env true 2>/dev/null || true
systemd-run --unit=matrix-periodic-status \
  --description="Private Matrix migration progress every 20 minutes" \
  --on-active=20m --on-unit-active=20m \
  /run/current-system/sw/bin/nix shell nixpkgs#python3 \
  --command python3 /etc/nixos/hosts/contabo/matrix-periodic-status.py
systemctl list-timers matrix-periodic-status.timer --no-pager
