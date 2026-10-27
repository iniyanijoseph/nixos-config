#!/usr/bin/env fish
# Phase 1: non-mutating readiness and photo metadata diagnostics.
#
# Run on Contabo as root after ff-only Git pull.
# Does not change NixOS generation, Nextcloud apps, photos or Matrix events.
set -gx TERM dumb
set -gx SYSTEMD_PAGER cat
set -gx GIT_OPTIONAL_LOCKS 0
set -gx PYTHONDONTWRITEBYTECODE 1

set -l repo /etc/nixos
set -l host "$repo/hosts/contabo"

function fatal -a message
    echo "ABORT: $message"
    exit 2
end

if test (count $argv) -ne 0
    fatal "No arguments accepted."
end
if test (id -u) -ne 0
    fatal "Run with sudo."
end
if test (hostname -s) != contabo
    fatal "Not the expected server."
end
if not test -f "$host/flake.nix"; or not test -f "$host/photo-metadata-audit.py"
    fatal "Review checkout missing essential files."
end
set -l branch (git -c safe.directory=$repo -C $repo branch --show-current 2>/dev/null)
if test $status -ne 0; or test "$branch" != main
    fatal "Git branch not confirmed main."
end
set -l changes (git -c safe.directory=$repo -C $repo status --porcelain=v1 --untracked-files=no 2>/dev/null)
if test $status -ne 0; or test (count $changes) -gt 0
    fatal "Tracked Git state changed or unreadable."
end
echo "=== PHASE 1: SAFE READINESS ==="
echo "Production Git:" (git -c safe.directory=$repo -C $repo rev-parse --short HEAD)
echo "No NixOS switch, photo write, app install, or Matrix mutation."

for service in matrix-synapse nginx mautrix-whatsapp postgresql
    set -l state (systemctl show --value -p ActiveState "$service.service" 2>/dev/null)
    echo "$service: $state"
    if test "$state" != active
        fatal "Core service unhealthy; investigate before photos."
    end
end

# Resolve OCC outside conditional scopes. Fish 'set -l' declared inside an
# if block goes out of scope at 'end' and leaves an empty command expansion.
# NixOS provides the OCC wrapper in the system profile.
set -l occ /run/current-system/sw/bin/nextcloud-occ
if not test -x "$occ"
    # A version-dependent wrapper may only be available via PATH.
    set -l found (command -s nextcloud-occ 2>/dev/null)
    if test -n "$found"; and test -x "$found"
        set occ "$found"
    else
        fatal "nextcloud-occ unavailable at expected path and in PATH."
    end
end
if test -z "$occ"
    fatal "OCC path resolved empty."
end
echo "OCC wrapper: executable found (path omitted)"

echo ""
echo "=== NEXTCLOUD STATUS ==="
$occ status
if test $status -ne 0
    fatal "Nextcloud status command failed."
end

echo ""
echo "=== GOOGLE REPLACEMENT APP STATUS ==="
set -l applist ($occ app:list --output=json 2>/dev/null)
set -l apps_rc $status
if test $apps_rc -eq 0; and command -sq jq
    printf '%s\n' $applist | jq -r '
      . as $root |
      ["memories","calendar","contacts","tasks","mail","notes","deck","news","files"][] as $app |
      if ($root.enabled|type) == "object" and ($root.enabled|has($app)) then
        "\($app): enabled"
      elif ($root.disabled|type) == "object" and ($root.disabled|has($app)) then
        "\($app): installed but disabled"
      else
        "\($app): not reported"
      end'
    if test $status -ne 0
        echo "WARNING: JSON app listing unavailable."
    end
else
    echo "App inventory JSON unavailable; showing filtered app listing."
    $occ app:list 2>/dev/null | grep -Ei 'memories|calendar|contacts|tasks|mail|notes|deck|news' | head -35
end

echo ""
echo "=== PHOTO TAKEOUT vs EXIF vs MTIME ==="
nix run "$host#contabo-photo-audit" -- --sample 500
set -l rc $status
if test $rc -ne 0
    echo "PHOTO AUDIT FAILED: no data was changed."
    exit $rc
end

echo ""
echo "=== BACKUP HEALTH / QUARANTINE ==="
set -l restic (systemctl show --value -p Result restic-backups-contabo.service 2>/dev/null)
echo "Last Restic job result: $restic"
if test -d /var/lib/migration-queue/photos-duplicate-quarantine
    echo "Photo quarantine: retained"
else
    echo "WARNING: Photo quarantine is absent; do not assume cleanup succeeded."
end

echo ""
echo "=== PHASE 1 COMPLETE ==="
echo "Use the reported counts to choose safe metadata remediation."
echo "Do NOT rerun Google Takeout migration or delete the quarantine."
