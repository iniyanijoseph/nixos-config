#!/usr/bin/env bash
# Compatibility entry point: all sources, Go modules and patches are Nix inputs.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/matrimail-build"
if [[ "$EUID" -eq 0 ]]; then
  echo 'Run this optional developer build as your normal user.' >&2
  exit 1
fi
mkdir -p "$OUT_DIR"
chmod 0700 "$OUT_DIR"
nix build -L "$SCRIPT_DIR/..#contabo-matrimail" --out-link "$OUT_DIR/package"
ln -sfn "$OUT_DIR/package/bin/matrimail" "$OUT_DIR/matrimail"
echo "Built pinned Matrimail: $OUT_DIR/matrimail"
echo 'Production uses the Nix package directly. No service was started.'
