# Discord bridge: personal account, historical import

This is a legacy mautrix-discord 0.7.6 bridge on the pinned NixOS 26.05
snapshot. It supports personal Discord DMs, group DMs, and selected guilds.

## Limits and risks

- Discord forbids automation of normal user accounts outside its bot API.
  Using the personal-account mode can result in account restrictions or bans.
- This package depends on deprecated, vulnerability-flagged libolm. The
  `discord.nix` module permits **only** the pinned `olm-3.2.16` package to
  build. This security exception does not fix the vulnerabilities.
- Large initial backfills are **bounded** at 100000 messages per new room;
  they are not guaranteed to fetch a whole lifetime, especially if Discord
  rate-limits the account. Initial fetching can be expensive on the VPS.
- Historical messages in Matrix are subject to the bridge's insertion
  behavior. Existing Matrix rooms cannot simply receive arbitrarily old
  messages at their original chronological location.
- The Discord bridge can read the plaintext of bridged messages. Protect
  bridge data and backups. Matrix-side encryption does not provide E2EE
  between a Discord correspondent and your Cinny device.

## Deploy

From Contabo:

```sh
cd /etc/nixos
sudo git pull --ff-only
sudo nixos-rebuild build --flake ./hosts/contabo#contabo
sudo nixos-rebuild switch --flake ./hosts/contabo#contabo
systemctl is-active mautrix-discord matrix-synapse nginx
sudo journalctl -u mautrix-discord -n 80 --no-pager
```

The NixOS module creates the registration file before Synapse starts; no
Discord credentials should be entered in shell commands or committed to Git.
Do not print appservice registration credentials or personal Discord tokens.

## Sign in

In Cinny, start a private chat with `@discordbot:iniyanjoseph.com`.
Send `help` then `login-qr`. Approve the QR code through Discord mobile.
QR login can fail if Discord requires an unsupported CAPTCHA. Avoid
publishing any user access token in chat, logs, screenshots, or Git.

The bridge creates a batch of recent DM portals at login. Further DMs may
be created as activity arrives. Server channels are not all automatically
bridged: use `guilds status` and `guilds bridge <id> --entire` in the
bridge management chat for each Discord server you want imported.

## Backfill verification

Inspect sanitized logs for backfill counts and errors:

```sh
sudo journalctl -u mautrix-discord --since "30 minutes ago" --no-pager \
  | grep -Ei 'backfill|portal|room|rate.limit|error|warn'
```

Accept room invitations in Cinny, then check one DM and one guild channel
with known old messages. A very high limit is an *attempt* at full history,
not proof of full history. If a bridge fails, examine service logs rather
than deleting bridge databases or rooms.

## Backup

```sh
sudo systemctl start restic-backups-contabo.service
sudo restic-contabo snapshots
sudo restic-contabo check
```

Restic includes `/var/lib/mautrix-discord`, bridge registration secrets,
Synapse state, and PostgreSQL logical dumps.
