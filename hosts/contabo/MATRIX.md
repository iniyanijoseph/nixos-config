# Matrix deployment on Contabo

**Chosen identity:** `@me:iniyanjoseph.com` (the Matrix server name is permanent).

- Synapse: `https://matrix.iniyanjoseph.com`
- Cinny: `https://chat.iniyanjoseph.com`
- PostgreSQL on the VPS; public registration off.
- Federation delegates via `https://iniyanjoseph.com/.well-known/matrix/server` to port 443.

## 1. DNS first

In Cloudflare DNS, create **DNS-only** A records (gray cloud) for:

```text
matrix  A  213.199.55.255
chat    A  213.199.55.255
```

Keep your apex `iniyanjoseph.com` pointed at GitHub Pages.
Don't publish AAAA records unless you have confirmed this VPS's IPv6 routing works.
The GitHub Pages website repo also contains `.well-known/matrix/server` and `client`.
After those files deploy, check both URLs return JSON over HTTPS.
The client response should advertise `https://matrix.iniyanjoseph.com`.
The server response should advertise `matrix.iniyanjoseph.com:443`.
Check `Content-Type: application/json` and `Access-Control-Allow-Origin: *` on
the client response. If GitHub Pages or your Cloudflare proxy omits these, set
a Cloudflare response-header transform/worker on those exact paths or move
discovery hosting to a server that can set the response headers correctly.

## 2. Generate the private registration secret

The secret is **not** your Matrix account password. It permits the one-time
terminal registration of private accounts. It is loaded with systemd
`LoadCredential` from a root-only file and must never be committed to Git.

On the VPS, Fish-compatible:

```fish
sudo install -d -m 700 -o root -g root /var/lib/secrets
sudo sh -c '
  set -eu
  umask 077
  secret=/var/lib/secrets/matrix-registration.yaml
  if [ -s "$secret" ]; then
    echo "Registration secret already exists; preserving it"
    exit 0
  fi
  if [ -e "$secret" ]; then
    echo "Refusing to overwrite existing empty registration secret"
    exit 1
  fi
  (printf "registration_shared_secret: "; head -c 48 /dev/urandom | base64) > "$secret"
'
sudo chmod 600 /var/lib/secrets/matrix-registration.yaml
sudo test -s /var/lib/secrets/matrix-registration.yaml
and echo 'Matrix registration secret OK'
```

Save an offline recovery copy of the secret. The existing Restic backup includes
`/var/lib/secrets`, but first take a new backup after a successful deployment.

## 3. Build and switch

```fish
cd /etc/nixos
sudo git pull --ff-only
sudo nixos-rebuild build --flake ./hosts/contabo#contabo
sudo nixos-rebuild switch --flake ./hosts/contabo#contabo
```

Do **not** change the `server_name` after the first Synapse startup.
After switching, check these before continuing:

```fish
systemctl is-active matrix-synapse.service
systemctl is-active matrix-synapse-database.service
systemctl is-active nginx postgresql phpfpm-nextcloud
sudo journalctl -u matrix-synapse.service -n 70 --no-pager
curl -fsS https://matrix.iniyanjoseph.com/_matrix/client/versions
curl -I https://chat.iniyanjoseph.com/
curl -i https://iniyanjoseph.com/.well-known/matrix/server
curl -i https://iniyanjoseph.com/.well-known/matrix/client
```

If TLS issuance fails, check Cloudflare DNS propagation, whether the records
are DNS-only, ports 80/443, and `journalctl -u acme-matrix.iniyanjoseph.com`.
If Synapse won't start, inspect `matrix-synapse-database.service` and its log.

## 4. Register your one admin account

Only after Synapse has started successfully:

```fish
sudo matrix-synapse-register_new_matrix_user -u me -a
```

Enter a strong account password at the prompt, not on the command line.
Sign in at `https://chat.iniyanjoseph.com` with `@me:iniyanjoseph.com`.
Verify messaging from two clients and save your encryption recovery key
or set up your secret storage recovery method in the Matrix client.

## 5. Backup and verification

```fish
sudo systemctl start restic-backups-contabo.service
sudo restic-contabo snapshots
sudo restic-contabo check
systemctl list-timers --all restic-backups-contabo.timer
```

Restic will now include Synapse media, signing keys and generated local state
at `/var/lib/matrix-synapse`; the PostgreSQL dump covers the new database.
Do not delete or rotate Synapse's signing key without a deliberate migration.
Your prior Nextcloud restore test is not a full Matrix disaster-recovery test;
we should separately verify that a Synapse signing key and database dump
can be recovered together after the first Matrix snapshot.

## 6. Follow-ups

Only after the basic homeserver works, add messaging bridges and consider
a TURN server for reliable calls. No mail server or Docker is required.
