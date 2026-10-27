#!/usr/bin/env fish
# Explicitly stop ONLY the old, transient private Matrix monitoring timer
# and command listener. Does not stop Synapse, bridge services or backups.
# Safe to rerun. Requires root (sudo). No NixOS deployment.
set -gx TERM dumb
set -gx SYSTEMD_PAGER cat

if test (count $argv) -ne 0
    echo "ABORT: No arguments are accepted."
    exit 2
end
if test (id -u) -ne 0
    echo "ABORT: Run as root using sudo."
    exit 2
end
if test (hostname -s) != contabo
    echo "ABORT: Not the expected Contabo host."
    exit 2
end
set -l timer matrix-periodic-status.timer
set -l listener matrix-command-listener.service
set -l periodic matrix-periodic-status.service

# Read-only identity checks before any systemctl stop.
for unit in $timer $listener
    set -l transient (systemctl show --value -p Transient "$unit" 2>/dev/null)
    set -l active (systemctl show --value -p ActiveState "$unit" 2>/dev/null)
    if test "$active" = inactive; or test "$active" = failed
        echo "Already stopped: $unit ($active)"
        continue
    end
    if test "$transient" != yes
        echo "ABORT: $unit is not transient; refusing to stop it."
        exit 2
    end
    if test "$active" != active
        echo "ABORT: Unexpected state $unit=$active."
        exit 2
    end
end

set -l listener_state (systemctl show --value -p ActiveState "$listener" 2>/dev/null)
if test "$listener_state" = active
    set -l command (systemctl show --value -p ExecStart "$listener" 2>/dev/null)
    if not string match -q '*matrix-commands.py*' -- "$command"
        echo "ABORT: Listener command does not match the old monitor."
        exit 2
    end
end

set -l timer_state (systemctl show --value -p ActiveState "$timer" 2>/dev/null)
if test "$timer_state" = active
    set -l target (systemctl show --value -p Unit "$timer" 2>/dev/null)
    if test "$target" != "$periodic"
        echo "ABORT: Timer points at unexpected unit."
        exit 2
    end
end

# Live infrastructure must remain intact. This script NEVER stops these units.
for unit in matrix-synapse.service mautrix-whatsapp.service nginx.service
    set -l current (systemctl show --value -p ActiveState "$unit" 2>/dev/null)
    if test "$current" != active
        echo "ABORT: Critical service $unit is not active ($current)."
        exit 2
    end
end
echo "PASS: Guarded identities and critical services checked."

# One explicitly authorized state change: stop only transient monitoring.
if test "$timer_state" = active
    systemctl stop "$timer"
    or begin
        echo "FAIL: Could not stop periodic monitoring timer."
        exit 1
    end
    echo "Stopped: $timer"
end

if test "$listener_state" = active
    systemctl stop "$listener"
    or begin
        echo "FAIL: Could not stop command listener."
        exit 1
    end
    echo "Stopped: $listener"
end

# The oneshot periodic service normally is inactive; refuse to stop it if
# currently active because it may be mid-delivery. The stopped timer will not
# spawn another job.
set -l periodic_state (systemctl show --value -p ActiveState "$periodic" 2>/dev/null)
if test "$periodic_state" = active
    echo "NOTICE: Periodic oneshot is finishing; no new timer runs will start."
end

echo "=== POST-STOP STATES ==="
for unit in "$timer" "$listener" matrix-synapse.service mautrix-whatsapp.service nginx.service
    set -l state (systemctl show --value -p ActiveState "$unit" 2>/dev/null)
    echo "$unit: $state"
end
echo "No NixOS switch, archive cleanup, bridge activation, or backup mutation."
