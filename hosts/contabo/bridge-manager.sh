# Runs on the graphical Linux laptop, not on Contabo.
set -euo pipefail
if [[ $(uname -n) == contabo || -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
  echo 'Run this on your graphical Linux laptop.' >&2
  exit 2
fi
task_bridge_tunnel_pid=
cleanup() {
  if [[ -n $task_bridge_tunnel_pid ]]; then
    kill "$task_bridge_tunnel_pid" 2>/dev/null || true
    wait "$task_bridge_tunnel_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM
ssh -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L 127.0.0.1:29321:127.0.0.1:29321 \
  -L 127.0.0.1:29320:127.0.0.1:29320 \
  wug@213.199.55.255 &
task_bridge_tunnel_pid=$!
task_bridge_ready=false
for ((attempt=0; attempt<120; attempt++)); do
  if ! kill -0 "$task_bridge_tunnel_pid" 2>/dev/null; then
    echo 'The SSH tunnel failed. Check SSH access and local port conflicts.' >&2
    exit 1
  fi
  # A 401/403 is expected without a Matrix login. Require the real bridge's
  # JSON auth error, not just a listener on a potentially unrelated port.
  if curl --silent --max-time 2 \
    'http://127.0.0.1:29321/_matrix/provision/v3/whoami?user_id=%40me%3Ainiyanjoseph.com' \
    | grep -q 'M_MISSING_TOKEN'; then
    task_bridge_ready=true
    break
  fi
  sleep 1
done
if [[ $task_bridge_ready != true ]]; then
  echo 'Slack manager API is not ready. Deploy finish-setup.sh on Contabo first.' >&2
  exit 1
fi
cat <<'INSTRUCTIONS'
Sign in to your Matrix homeserver: https://matrix.iniyanjoseph.com
Matrix user: @me:iniyanjoseph.com
Add your own Slack bridge URL: http://127.0.0.1:29321
Optional Google Messages bridge URL: http://127.0.0.1:29320
Start a fresh login in the app. Complete any CAPTCHA yourself in its browser.
Keep this launcher open until login finishes; the bridge session stays on Contabo.
INSTRUCTIONS
mautrix-manager
