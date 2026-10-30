#!/usr/bin/env bash
# Build a PINNED Matrimail revision in the pinned Contabo development shell.
# Does not touch Synapse, switch NixOS, or start a background service.
set -euo pipefail

REV="6f22bb7115063241eb91d146ad1f177a56ae3ad5"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FLAKE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SRC_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/matrimail-source"
OUT_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/matrimail-build"

if [[ "${EUID}" -eq 0 ]]; then
  echo "Do not build as root. Run as your normal user." >&2
  exit 1
fi
mkdir -p -- "$(dirname -- "$SRC_DIR")" "$OUT_DIR"
chmod 0700 "$OUT_DIR"
if [[ ! -d "$SRC_DIR/.git" ]]; then
  git clone https://github.com/Leicas/matrimail.git "$SRC_DIR"
fi
git -C "$SRC_DIR" fetch --depth=1 origin "$REV"
git -C "$SRC_DIR" checkout --detach --force "$REV"
if [[ "$(git -C "$SRC_DIR" rev-parse HEAD)" != "$REV" ]]; then
  echo "Unexpected source revision" >&2
  exit 1
fi

echo "Building Matrimail $REV with Nix-pinned Go and libolm..."
nix develop "$FLAKE_DIR#email-bridge" --command bash -c '
  set -euo pipefail
  cd "$1"
  patch --batch --forward -p1 < "$3/contabo.patch"
  cp "$3/imap_backfill.go" pkg/imap/contabo_backfill.go
  cp "$3/imap_backfill_test.go" pkg/imap/contabo_backfill_test.go
  cp "$3/connector_backfill.go" pkg/connector/contabo_backfill.go
  gofmt -w pkg/imap/contabo_backfill*.go pkg/connector/contabo_backfill.go
  CGO_ENABLED=1 go test ./pkg/imap ./pkg/connector -run TestContabo -count=1
  CGO_ENABLED=1 go build -trimpath -o "$2/matrimail" ./cmd/matrimail
' bash "$SRC_DIR" "$OUT_DIR" "$SCRIPT_DIR"
chmod 0750 "$OUT_DIR/matrimail"
echo "Built: $OUT_DIR/matrimail"
echo "This binary has NOT been installed or started."
