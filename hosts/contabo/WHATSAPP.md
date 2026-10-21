# WhatsApp bridge on Contabo

This adds mautrix-whatsapp to the existing private Matrix server. WhatsApp
runs as a linked device on your phone; it does not require Docker, new public
ports, new DNS entries, or an additional Nginx virtual host.

## 1. Provision encryption secret (once; never commit it)

Run on Contabo. This is fish-compatible and idempotent:

```sh
sudo install -d -m 0700 -o root -g root /var/lib/secrets
sudo sh -c '
  set -eu
  umask 077
  secret=/var/lib/secrets/mautrix-whatsapp.env
  if [ -e "$secret" ]; then
    test -s "$secret" || { echo "Empty WhatsApp secret file"; exit 1; }
    echo "WhatsApp bridge secret already exists; preserving it"
    exit 0
  fi
  (printf "WHATSAPP_PICKLE_KEY="; head -c 48 /dev/urandom | base64 -w0; printf "\n") > "$secret"
'
sudo chmod 0600 /var/lib/secrets/mautrix-whatsapp.env
```

Store an offline copy securely. The encryption pickle key must not change after
the bridge starts using it. Restic already backs up /var/lib/secrets.

## 2. Deploy

```sh
cd /etc/nixos
sudo git pull --ff-only
sudo nixos-rebuild build --flake ./hosts/contabo#contabo
sudo nixos-rebuild switch --flake ./hosts/contabo#contabo
systemctl is-active mautrix-whatsapp matrix-synapse nginx
sudo journalctl -u mautrix-whatsapp -n 80 --no-pager
```

Check Synapse after switching. On the first deployment, if registration file
creation races with Synapse startup, verify that
`/var/lib/mautrix-whatsapp/whatsapp-registration.yaml` exists and then restart
Synapse (`sudo systemctl restart matrix-synapse`). Do not print the
registration file; it contains tokens.

## 3. Connect your account

In Cinny at https://chat.iniyanjoseph.com, start a private direct chat with
`@whatsappbot:iniyanjoseph.com`. Send `login qr`.

On your phone, open WhatsApp → Settings / menu → Linked devices → Link a
device, then scan the bridge bot's QR code. Alternatively use `login phone`
and follow the pairing-code prompts. Existing WhatsApp chats should begin
appearing in Matrix shortly after pairing.

Keep your phone's WhatsApp installation. It must reconnect at least once every
two weeks to avoid linked-device logout.

## 4. Confirm backup and privacy

```sh
sudo systemctl start restic-backups-contabo.service
sudo restic-contabo snapshots
sudo restic-contabo check
```

The existing PostgreSQL dump covers Synapse; Restic also includes
`/var/lib/mautrix-whatsapp` and `/var/lib/secrets`.
Messages sent through the bridge are decrypted by it; this is not
end-to-end encryption between a WhatsApp user and your Cinny device. Keep
the VPS, database, and backups private.

If the login fails, check `journalctl -u mautrix-whatsapp -n 100 --no-pager`
and redact phone numbers and tokens before sharing logs.
