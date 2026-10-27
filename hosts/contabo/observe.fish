#!/usr/bin/env fish
# Comprehensive READ-ONLY Contabo inventory. Does not start/stop services,
# switch NixOS, run OCC, change permissions, clean files, or import anything.
#
# Run as: sudo /run/current-system/sw/bin/fish -n ./observe.fish
#         sudo /run/current-system/sw/bin/fish ./observe.fish
#
# Output is intentionally sanitized for sharing: no message bodies, paths to
# private chats, tokens, individual photo names, IPs, or secret contents.
# Do not add "set -x"/command tracing: some environments contain secrets.
# Most checks are local; remote backup metadata is NOT queried in this script.

set -gx TERM dumb
set -gx SYSTEMD_PAGER cat
set -gx PAGER cat
set -gx GIT_OPTIONAL_LOCKS 0
set -gx PYTHONDONTWRITEBYTECODE 1

set -g repo /etc/nixos
set -g host $repo/hosts/contabo
set -g state /var/lib/migration-queue
set -g archive /var/lib/discord-archive/archive.sqlite
set -g photo '/var/lib/nextcloud/data/wug/files/Photos/Google Photos'
set -g passed 0
set -g warned 0
set -g blocked 0

function emit -a level text
    printf '[%-5s] %s\n' "$level" "$text"
    switch $level
        case PASS
            set -g passed (math $passed + 1)
        case WARN
            set -g warned (math $warned + 1)
        case BLOCK
            set -g blocked (math $blocked + 1)
    end
end

function heading -a name
    printf '\n===== %s =====\n' "$name"
end

function command_exists -a name
    command -sq $name
end

function check_path -a label path kind
    if test -L "$path"
        emit WARN "$label: symlink (not followed)"
    else if test "$kind" = dir
        if test -d "$path"
            emit PASS "$label: present directory"
        else
            emit WARN "$label: directory missing"
        end
    else if test -f "$path"
        emit PASS "$label: present file"
    else
        emit WARN "$label: file missing"
    end
end

function check_secret -a label path
    # Never inspect, parse, print or source secret content.
    if test -L "$path"
        emit BLOCK "$label: unexpected symlink"
        return
    end
    if not test -f "$path"
        emit WARN "$label: absent"
        return
    end
    if not command_exists stat
        emit WARN "$label: stat unavailable"
        return
    end
    set -l mode (stat -c '%a' -- "$path" 2>/dev/null)
    set -l owner (stat -c '%U' -- "$path" 2>/dev/null)
    if test "$owner" != root
        emit WARN "$label: owner=$owner, mode=$mode"
    else if string match -qr '^[0-7]{1,2}00$' -- "$mode"
        emit PASS "$label: root owned; group/other access denied"
    else
        emit WARN "$label: mode=$mode; check group/other permissions"
    end
end

function unit_status -a unit expected
    if not command_exists systemctl
        emit WARN "$unit: systemctl missing"
        return
    end
    set -l load (systemctl show "$unit" --no-pager -p LoadState --value 2>/dev/null)
    set -l active (systemctl show "$unit" --no-pager -p ActiveState --value 2>/dev/null)
    set -l source (systemctl show "$unit" --no-pager -p FragmentPath --value 2>/dev/null)
    set -l enabled (systemctl is-enabled "$unit" 2>/dev/null)
    if test -z "$load"
        emit WARN "$unit: cannot query systemd"
        return
    end
    if test "$load" = not-found
        if test "$expected" = required
            emit BLOCK "$unit: missing"
        else
            emit PASS "$unit: not installed (staged/disabled)"
        end
        return
    end
    if test "$active" = active
        if test "$expected" = disabled
            emit WARN "$unit: ACTIVE though intended disabled"
        else
            emit PASS "$unit: active, enabled=$enabled"
        end
    else if test "$expected" = required
        emit BLOCK "$unit: $active, enabled=$enabled"
    else if test "$active" = failed
        emit WARN "$unit: FAILED, enabled=$enabled"
    else
        emit PASS "$unit: $active, enabled=$enabled"
    end
    if string match -q '/run/systemd/transient/*' -- "$source"
        emit WARN "$unit: transient, not declarative/reboot persistent"
    end
end

function check_marker -a label filename
    set -l path "$state/$filename"
    if test -L "$path"
        emit BLOCK "$label: checkpoint is symlink"
    else if not test -f "$path"
        emit WARN "$label: checkpoint absent"
    else if command_exists jq
        if jq -e 'type == "object"' "$path" >/dev/null 2>/dev/null
            # Deliberately omit filename/user/content/checkpoint text.
            set -l when (jq -r '.finished // .checked // .sent_at // "unknown"' "$path" 2>/dev/null)
            emit PASS "$label: checkpoint present, timestamp=$when"
        else
            emit WARN "$label: invalid or unreadable JSON"
        end
    else
        emit WARN "$label: file exists, jq absent (JSON not checked)"
    end
end

if test (count $argv) -ne 0
    printf '%s\n' 'This audit accepts no arguments. It makes no changes.'
    exit 2
end

heading "AUDIT GUARD"
if not test -e /etc/NIXOS
    emit BLOCK "Not NixOS, stopped"
    exit 2
end
if not command_exists hostname
    emit BLOCK "Cannot identify host, stopped"
    exit 2
end
set -l machine (hostname -s 2>/dev/null)
if test "$machine" != contabo
    emit BLOCK "Unexpected host name, stopped"
    exit 2
end
if not test -f "$host/flake.nix"
    emit BLOCK "Expected host flake missing, stopped"
    exit 2
end
emit PASS "NixOS host and Contabo flake confirmed"
if test (id -u) != 0
    emit WARN "Run with sudo for protected metadata; no privilege changes made"
else
    emit PASS "Root metadata access"
end
date -u '+UTC time: %Y-%m-%dT%H:%M:%SZ'
if command_exists uptime
    uptime -p 2>/dev/null
end

heading "VERSION / REPRODUCIBILITY"
if command_exists nixos-version
    printf 'NixOS: %s\n' (nixos-version 2>/dev/null)
end
if command_exists nix
    printf 'Nix: %s\n' (nix --version 2>/dev/null)
end
if command_exists git
    set -l root (git -c safe.directory=$repo -C $repo rev-parse --show-toplevel 2>/dev/null)
    if test "$root" = "$repo"
        emit PASS "Git worktree recognized"
        set -l rev (git -c safe.directory=$repo -C $repo rev-parse --short=12 HEAD 2>/dev/null)
        set -l branch (git -c safe.directory=$repo -C $repo branch --show-current 2>/dev/null)
        printf 'Production Git: branch=%s commit=%s\n' "$branch" "$rev"
        set -l changed (git -c safe.directory=$repo -C $repo status --porcelain=v1 --untracked-files=no 2>/dev/null)
        if test (count $changed) -eq 0
            emit PASS "Production tracked files clean"
        else
            emit WARN "Production tracked file changes: "(count $changed)
        end
        set -l untracked (git -c safe.directory=$repo -C $repo ls-files --others --exclude-standard 2>/dev/null)
        printf 'Untracked file count (names hidden): %s\n' (count $untracked)
    else
        emit BLOCK "Git checkout unreadable or unexpected"
    end
    set -l review /var/tmp/contabo-pr1-review
    if test -d "$review"
        set -l id (git -c safe.directory=$review -C "$review" rev-parse --short=12 HEAD 2>/dev/null)
        if test -n "$id"
            emit PASS "Review worktree present at commit=$id"
        else
            emit WARN "Review worktree exists but cannot resolve commit"
        end
    end
else
    emit WARN "Git unavailable"
end
check_path 'Contabo flake lock' "$host/flake.lock" file
check_path 'Optional declarative monitoring module' "$host/monitoring.nix" file
check_path 'Operations runbook' "$host/OPERATIONS.md" file
if test -L /run/current-system
    set -l deployed (readlink /run/current-system 2>/dev/null)
    printf 'Deployed NixOS generation: %s\n' (basename "$deployed")
end
if command_exists nixos-rebuild
    emit PASS "nixos-rebuild installed; intentionally not invoked"
end
emit PASS "No build, switch, git fetch, git pull, or flake evaluation performed"

heading "CORE SERVICES"
for name in         'matrix-synapse.service|required'         'matrix-synapse-database.service|optional'         'nginx.service|required'         'postgresql.service|required'         'nextcloud-cron.timer|required'         'nextcloud-cron.service|optional'         'redis-nextcloud.service|optional'         'mautrix-whatsapp.service|required'         'restic-backups-contabo.timer|required'         'restic-backups-contabo.service|optional'         'discord-photos-queue.service|disabled'         'matrix-command-listener.service|optional'         'matrix-periodic-status.timer|optional'         'matrix-periodic-status.service|optional'         'mautrix-discord.service|disabled'         'mautrix-gmessages.service|disabled'         'mautrix-slack.service|disabled'         'matrimail.service|disabled'         'stalwart.service|disabled'
    set -l parts (string split -m1 '|' -- "$name")
    unit_status "$parts[1]" "$parts[2]"
end

heading "MONITORING AND COLLECTOR"
if command_exists pgrep
    set -l collectors (pgrep -fc '[d]iscord-archive/collector.py' 2>/dev/null)
    if string match -qr '^[0-9]+$' -- "$collectors"
        printf 'Discord collector processes matching archived script: %s\n' "$collectors"
        if test "$collectors" -gt 0
            emit PASS "Discord collection process detected (NOT proof of healthy progress)"
        else
            emit WARN "No Discord collector process detected"
        end
    else
        emit WARN "Could not check collector processes"
    end
end
if command_exists systemctl
    set -l mon (systemctl show matrix-command-listener.service --no-pager -p ActiveState --value 2>/dev/null)
    set -l timer (systemctl show matrix-periodic-status.timer --no-pager -p ActiveState --value 2>/dev/null)
    printf 'Private monitoring: listener=%s periodic_timer=%s\n' "$mon" "$timer"
end
emit PASS "Process command lines and tokens intentionally not printed"

heading "DATA, CHECKPOINTS, DISCORD COVERAGE"
for entry in         'Synapse|/var/lib/matrix-synapse'         'Nextcloud|/var/lib/nextcloud'         'WhatsApp|/var/lib/mautrix-whatsapp'         'Discord archive|/var/lib/discord-archive'         'Migration checkpoints|/var/lib/migration-queue'
    set -l pair (string split -m1 '|' -- "$entry")
    check_path "$pair[1]" "$pair[2]" dir
end
check_path 'Historical Discord SQLite archive' "$archive" file
if test -f "$archive"; and command_exists stat
    printf 'Historical Discord DB bytes: %s\n' (stat -c '%s' -- "$archive" 2>/dev/null)
end
if test -f "$archive"; and command_exists sqlite3
    set -l cnt (sqlite3 -readonly "$archive" 'PRAGMA query_only=ON; SELECT COUNT(*) FROM messages;' 2>/dev/null)
    if string match -qr '^[0-9]+$' -- "$cnt"
        printf 'Historical Discord message rows: %s\n' "$cnt"
    else
        emit WARN "SQLite message query failed or database busy"
    end
    set -l channels (sqlite3 -readonly "$archive" 'PRAGMA query_only=ON; SELECT COUNT(*) FROM channels;' 2>/dev/null)
    if string match -qr '^[0-9]+$' -- "$channels"
        printf 'Discovered Discord channel rows: %s\n' "$channels"
    end
    set -l bad (sqlite3 -readonly "$archive" 'PRAGMA query_only=ON; SELECT COUNT(*) FROM scans WHERE ok != 1;' 2>/dev/null)
    if string match -qr '^[0-9]+$' -- "$bad"
        printf 'Failed Discord discovery scan rows: %s\n' "$bad"
        if test "$bad" -gt 0
            emit WARN "Discord discovery incomplete; do not enable cutover"
        end
    end
else if test -f "$archive"
    emit WARN "sqlite3 unavailable: archive schema and counters not queried"
end
for entry in         'Photo original reconciliation|photos-reconciled.json'         'Takeout metadata migration|photos-migrated.json'         'Memories indexing|photos-indexed.json'         'Photo metadata manual audit|photos-metadata-audited.json'         'Duplicate quarantine removal|photos-quarantine-cleaned.json'         'Offline mail/bridge preflight|services-staged.json'         'Native Discord event import audit|discord-native-import-verified.json'         'Migration final notification|matrix-periodic-final-sent.json'
    set -l pair (string split -m1 '|' -- "$entry")
    check_marker "$pair[1]" "$pair[2]"
end
if test -d "$state/photos-duplicate-quarantine"
    emit WARN "Duplicate photo quarantine retained; deletion NOT authorized by this audit"
    if command_exists du; and command_exists awk
        set -l qsize (du -sh -- "$state/photos-duplicate-quarantine" 2>/dev/null | awk '{print $1}')
        if test (count $qsize) -ge 1
            printf 'Photo quarantine approximate disk usage: %s\n' "$qsize[1]"
        end
    end
else
    emit WARN "Duplicate quarantine absent; check prior cleanup before assuming safe removal"
end
if test -d "$photo"
    emit PASS "Canonical Nextcloud Google Photos location present"
else
    emit WARN "Canonical photos directory missing/unreadable"
end
if test -f "$state/photos-manifest.json"; and command_exists jq
    set -l total (jq -r '(.files // {}) | length' "$state/photos-manifest.json" 2>/dev/null)
    if string match -qr '^[0-9]+$' -- "$total"
        printf 'Manifest original file count: %s\n' "$total"
    end
end
if test -d "$photo"; and command_exists find
    set -l candidate (find "$photo" -type f -name 'PXL_20260119_181023267.jpg' -print -quit 2>/dev/null)
    if test (count $candidate) -gt 0
        if command_exists exiftool
            set -l stamp (exiftool -s3 -DateTimeOriginal -- "$candidate[1]" 2>/dev/null)
            if string match -q '2026:01:19*' -- "$stamp"
                emit PASS "Historical photo: original EXIF date matches 2026-01-19"
            else
                emit WARN "Historical photo: EXIF date absent or unexpected"
            end
        else
            emit WARN "exiftool absent: unable to inspect historical sample"
        end
    else
        emit WARN "Historical photo sample unavailable (may have been renamed)"
    end
end
emit WARN "EXIF sample and indexing checkpoint cannot prove all Memories dates/GPS are correct"

heading "SECRETS: METADATA ONLY"
for entry in         'Restic encryption password|/var/lib/secrets/restic-password'         'Restic R2 access|/var/lib/secrets/restic-r2.env'         'Matrix appservice registration|/var/lib/secrets/matrix-registration.yaml'         'Private Matrix reporting|/var/lib/secrets/matrix-alerts.json'         'WhatsApp encryption key|/var/lib/secrets/mautrix-whatsapp.env'         'Nextcloud admin file|/var/lib/secrets/nextcloud-admin'
    set -l pair (string split -m1 '|' -- "$entry")
    check_secret "$pair[1]" "$pair[2]"
end
emit PASS "No credential content, private chat data or user profile data read for output"

heading "BACKUP AND RESTORE READINESS"
check_path 'NixOS backup module' "$host/backups.nix" file
if test -f "$host/backups.nix"; and command_exists grep
    for dir in /var/lib/nextcloud /var/lib/matrix-synapse /var/lib/mautrix-whatsapp /var/lib/discord-archive /var/lib/migration-queue /var/lib/secrets
        if grep -Fq "\"$dir\"" "$host/backups.nix" 2>/dev/null
            emit PASS "Configured restic coverage: $dir"
        else
            emit WARN "Backup path not found in module: $dir"
        end
    end
    if grep -Fq '"/var/lib/mautrix-discord"' "$host/backups.nix" 2>/dev/null
        emit PASS "Future live Discord mapping directory appears in backup module"
    else
        emit WARN "Live Discord mapping directory not yet included"
    end
end
if command_exists systemctl
    set -l last (systemctl show restic-backups-contabo.service --no-pager -p ExecMainExitTimestamp --value 2>/dev/null)
    set -l res (systemctl show restic-backups-contabo.service --no-pager -p Result --value 2>/dev/null)
    set -l next (systemctl show restic-backups-contabo.timer --no-pager -p NextElapseUSecRealtime --value 2>/dev/null)
    printf 'Last restic unit exit: %s | result: %s\n' "$last" "$res"
    printf 'Next restic timer: %s\n' "$next"
end
emit WARN "Offsite R2 snapshots NOT queried; this report does not prove a tested restore"
emit WARN "Restic over active SQLite and a separately dumped PostgreSQL database is not an atomic cross-service backup"

heading "PUBLIC SERVICE HEALTH (HTTP HEAD, no tokens)"
if command_exists curl
    for entry in             'Matrix client API|https://matrix.iniyanjoseph.com/_matrix/client/versions'             'Cinny UI|https://chat.iniyanjoseph.com/'             'Nextcloud UI|https://cloud.iniyanjoseph.com/'
        set -l pair (string split -m1 '|' -- "$entry")
        set -l code (curl --head --max-time 10 --silent --show-error --output /dev/null --write-out '%{http_code}' -- "$pair[2]" 2>/dev/null)
        if string match -qr '^[23][0-9][0-9]$' -- "$code"
            emit PASS "$pair[1]: HTTP $code"
        else
            emit WARN "$pair[1]: HTTP $code (HEAD may not be supported)"
        end
    end
else
    emit WARN "curl missing: public service probes skipped"
end

heading "DISK / RESOURCES"
if command_exists df; and command_exists awk
    df -hP / /var/lib 2>/dev/null | awk 'NR == 1 || !seen[$1]++ { print }'
end
if command_exists free
    free -h 2>/dev/null
end
if command_exists ss
    set -l ports (ss -lntH 2>/dev/null | wc -l | string trim)
    printf 'TCP listening socket count (no addresses displayed): %s\n' "$ports"
end
emit WARN "Native Discord importer, bridge cutover, attachment backfill and full restore are NOT established"
emit WARN "Staged Stalwart/Matrimail/Slack/SMS must not be enabled without registrations, secrets and tests"

heading "FINAL"
printf 'Summary: %s passed, %s warnings, %s blockers\n' $passed $warned $blocked
printf '%s\n' 'This script made no intentional application, Git or system configuration changes.'
printf '%s\n' 'Share the output for a guarded setup plan; do not delete archives or quarantine.'
if test $blocked -gt 0
    exit 2
end
exit 0
