# Private Matrix notifications from Contabo

`migration-queue.py` can send completion/failure alerts if `/var/lib/secrets/matrix-alerts.json` exists. Without it, migration continues normally.

Create a **separate non-admin bot account** (for example `@server-alerts:iniyanjoseph.com`) and invite it to a private 'Server Alerts' room shared with `@me:iniyanjoseph.com`. Messages from your own account usually don't generate push notifications.

Synapse has public registration disabled. Use its administrative registration procedure for the bot, not public signup; check the installed Synapse registration commands and configuration. Obtain a bot access token (through Matrix login) and the internal room ID, which starts with `!`. Do not share tokens or room secrets in chat or commit them to Git.

On Contabo:

```fish
sudo install -d -m 0700 /var/lib/secrets
sudoedit /var/lib/secrets/matrix-alerts.json
```

Create the file with this structure:

```json
{
  "homeserver": "https://matrix.iniyanjoseph.com",
  "room_id": "!ROOM_ID:iniyanjoseph.com",
  "access_token": "BOT_ACCESS_TOKEN"
}
```

Then restrict permissions and test:

```fish
sudo chown root:root /var/lib/secrets/matrix-alerts.json
sudo chmod 0600 /var/lib/secrets/matrix-alerts.json
sudo python3 /etc/nixos/hosts/contabo/matrix-alert.py '[Contabo] Notification test'
```

Pull updates, run unit tests, then restart **only** the existing migration queue:

```fish
cd /etc/nixos
sudo git pull --ff-only
nix shell nixpkgs#python3 --command python3 -m unittest hosts/contabo/test_migration_queue.py -v
sudo systemctl restart discord-photos-queue
```

Messages are emitted for verified/reconciled photos, Takeout metadata migration, Memories indexing, service preflight completion, and a queue failure. Notifications are best-effort and deduplicated across retries. The failure event is only sent once until its marker is deliberately reset. Errors must still be checked via systemd logs. Never send Discord message contents or tokens in alerts.

For future services, invoke this same script from systemd `OnFailure` handlers or service hooks. A VPS-wide outage also requires an external heartbeat checker; an unavailable Synapse server cannot notify you of its own outage.

No NixOS switch is required for the existing queue. Git commits alone do not configure the bot or change running services.