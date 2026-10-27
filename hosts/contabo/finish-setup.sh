#!/usr/bin/env bash
# One entry point; the worker survives logout. Boot resume is declarative.
set -euo pipefail
export PATH="/run/current-system/sw/bin:$PATH"
export SYSTEMD_PAGER=cat
repo=/etc/nixos
state=/var/lib/migration-queue/finish-setup
unit=contabo-finish-setup.service
if [[ ${EUID} != 0 || $(hostname -s) != contabo ]]; then
    echo 'Run this with sudo on Contabo.' >&2
    exit 2
fi
case "${1:-}" in
    --status)
        systemctl status "$unit" --no-pager || true
        if [[ -f $state/summary.txt ]]; then cat "$state/summary.txt"; fi
        exit 0 ;;
    '') ;;
    *) echo 'Usage: finish-setup.sh [--status]' >&2; exit 2 ;;
esac
install -d -m 0700 "$state"
exec 9>"$state/launcher.lock"
flock -n 9 || { echo 'Another launcher is already displaying this run; use --status.'; exit 2; }
touch "$state/run.log"
chmod 0600 "$state/run.log"
if ! systemctl is-active --quiet "$unit" &&
   [[ $(systemctl show "$unit" --value -p ActiveState 2>/dev/null) != activating ]]; then
    [[ $(git -c safe.directory="$repo" -C "$repo" branch --show-current) == main ]]
    [[ -z $(git -c safe.directory="$repo" -C "$repo" status --porcelain --untracked-files=no) ]]
    echo 'Building the pinned setup runner; integration deployment will build and switch NixOS with rollback checks.'
    nix build "$repo/hosts/contabo#contabo-finish-setup" --out-link "$state/runner"
    # Resolve the closure now: a later pull or rebuild cannot change a running job.
    runner=$(readlink -f "$state/runner")
    cat > "$state/unit.tmp" <<EOF
[Unit]
Description=Finish Contabo setup; summary in $state/summary.txt
Wants=network-online.target
After=network-online.target
ConditionHost=contabo

[Service]
Type=oneshot
ExecStart=$runner/bin/contabo-finish-setup
Environment=PATH=/run/current-system/sw/bin
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=SYSTEMD_PAGER=cat
UMask=0077
TimeoutStartSec=infinity
StandardOutput=append:$state/run.log
StandardError=append:$state/run.log

[Install]
WantedBy=multi-user.target
EOF
    # NixOS owns /etc/systemd/system in the read-only Nix store. Runtime
    # units belong under /run; never remount /nix/store or write into /etc.
    install -d -m 0755 /run/systemd/system
    install -m 0644 "$state/unit.tmp" "/run/systemd/system/$unit"
    rm "$state/unit.tmp"
    systemctl daemon-reload
    # A future ordinary NixOS deployment installs finish-setup.nix for
    # reboot resume. Runtime systemctl enable would write into read-only /etc.
    touch "$state/resume-on-boot"
    systemctl start --no-block "$unit"
fi
echo 'Setup is running under systemd. Closing this terminal will not stop it.'
if systemctl is-enabled --quiet "$unit"; then
    echo 'Declarative boot resume is installed.'
else
    echo 'Runtime unit only: after a reboot, run this command again to resume.'
    echo 'Automatic boot resume becomes available after deploying finish-setup.nix.'
fi
echo "Progress: sudo bash $repo/hosts/contabo/finish-setup.sh --status"
echo "Private log: $state/run.log"
tail -n 20 -F "$state/run.log" &
log_pid=$!
trap 'kill "$log_pid" 2>/dev/null || true' EXIT
trap 'exit 130' INT TERM
while [[ $(systemctl show "$unit" --value -p ActiveState) == activating ]]; do
    sleep 2
done
if [[ -f $state/summary.txt ]]; then cat "$state/summary.txt"; fi
[[ $(systemctl show "$unit" --value -p Result) == success ]]
