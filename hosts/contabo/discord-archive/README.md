# Discord: retired bridge and manual archive workflow

This directory is intentionally **not** a systemd service or timer. The old
mautrix-discord bridge is disabled in \`../discord.nix\`. Nothing runs unless
an operator executes these commands. Run them on Contabo from \`/etc/nixos\`.
The collector and the optional Matrix-room cleanup are independent.

**Status:** The collector is an API-dependent, locally tested prototype;
it has NOT been tested against the live Discord account. It cannot guarantee
retrieval of old closed DMs, deleted/inaccessible messages, media files,
or 100% of Discord history. It does not import any messages into Matrix.
Discord forbids automating personal accounts; doing so may terminate the
account. Never put a Discord session token in Git or shell arguments.

## 1. Retire the old bridge (NixOS rebuild only once)

\`\`\`fish
cd /etc/nixos
sudo systemctl stop mautrix-discord
sudo git pull --ff-only
sudo nixos-rebuild build --flake ./hosts/contabo#contabo
sudo nixos-rebuild switch --flake ./hosts/contabo#contabo
systemctl is-active mautrix-discord
\`\`\`

Expected bridge status is \`inactive\` or \`unknown\`. Synapse, WhatsApp,
Nextcloud, and the existing encrypted Restic backups remain configured.

## 2. Create a persistent, backed-up archive directory

\`\`\`fish
sudo install -d -m 0700 -o wug -g users /var/lib/discord-archive
\`\`\`

The Restic configuration includes this path once the updated NixOS config is
deployed. The SQLite archive is plaintext locally (0700 directory, 0600
files) and encrypted by Restic before offsite backup.

## 3. Inspect old Discord-created Matrix rooms (read-only)

Do this **before deleting the legacy bridge database**, since it provides the
precise list of room IDs. The script refuses to use arbitrary room-name
matching.

\`\`\`fish
sudo nix shell nixpkgs#python3 --command python3 \
  hosts/contabo/discord-archive/reset_rooms.py inventory
sudo cat /var/lib/discord-archive/old-matrix-rooms.json
\`\`\`

This includes Discord portal rooms, guild spaces, your Discord-management
room and DM spaces from the bridge's SQLite DB.

## 4. Remove old Discord rooms from Synapse (optional, destructive)

Requires a **Matrix Synapse admin** account access token (not the Discord
token). This is not a password and must never be pasted into a chat.
The script prompts securely. It calls Synapse's admin room deletion endpoint
and waits for each deletion to finish.

\`\`\`fish
sudo nix shell nixpkgs#python3 --command python3 \
  hosts/contabo/discord-archive/reset_rooms.py purge
\`\`\`

It asks for \`PURGE DISCORD\` and the Matrix **admin** token before deleting.
If the token lacks admin privileges, the script stops before deleting.
The tool only purges room IDs in the previously saved manifest and doesn't
purge other Matrix rooms. Matrix ghost user account records may remain.

Once the purge is complete, and **after you have saved the room inventory**,
you may completely delete the old local bridge state:

\`\`\`fish
sudo rm -rf -- /var/lib/mautrix-discord
\`\`\`

Only execute that exact command after successful service retirement.
This does not erase older offsite Restic snapshots, which follow their
existing retention policy.

## 5. Collect Discord history manually (no Matrix writes)

Run the script directly from the checkout. It uses a hidden token prompt,
uses one API request at a time, retries temporary failures, and checkpoints
SQLite pages before advancing the cursor.

\`\`\`fish
nix shell nixpkgs#python3 --command python3 \
  hosts/contabo/discord-archive/collector.py \
  --db /var/lib/discord-archive/archive.sqlite run
\`\`\`

To review status without Discord credentials:

\`\`\`fish
nix shell nixpkgs#python3 --command python3 \
  hosts/contabo/discord-archive/collector.py \
  --db /var/lib/discord-archive/archive.sqlite report

nix shell nixpkgs#python3 --command python3 \
  hosts/contabo/discord-archive/collector.py \
  --db /var/lib/discord-archive/archive.sqlite verify
\`\`\`

To continue after interruption, rerun the same \`run\` command. It runs
discovery, resumes incomplete historical channels, then catches up on newer
messages. Exit code 2 means some known channels or discovery scopes remain
incomplete. The detailed status lives at
\`/var/lib/discord-archive/status.json\`.

For a long run, \`tmux\` avoids SSH disconnection:

\`\`\`fish
nix shell nixpkgs#tmux --command tmux new -s discord-archive
\`\`\`

**Completeness limitation:** A green verification only proves that the
collector exhausted history for *registered, visible* channels. Dormant old
DMs can be omitted from Discord's current API inventory; the official
account-data package is useful to identify missing channels. The collector
does not guarantee historical data that Discord no longer exposes.
No Matrix importer is started here.

## Offline tests

\`\`\`fish
nix shell nixpkgs#python3 --command python3 \
  -m unittest discover -s hosts/contabo/discord-archive -p 'test_*.py' -v
\`\`\`

The tests simulate API interruption/retry, bad pagination, guild discovery,
and catch-up checkpoints. They do not contact Discord or Synapse.
