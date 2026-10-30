# Browser login and retained email history

Deploy on Contabo after merging, using the existing launcher:

```fish
cd /etc/nixos
and sudo git -c safe.directory=/etc/nixos pull --ff-only origin main
and sudo bash hosts/contabo/finish-setup.sh
```

The runner enables Matrix-authenticated provisioning on the existing Slack
and Google Messages loopback listeners. The generated API secrets remain in
the private configuration files; the manager authenticates using your Matrix
session. Debug endpoints remain disabled. No public bridge port or firewall
rule is added. Existing bridge sessions, registrations and databases are retained.
Only bridges whose manager settings changed are restarted; a changed Matrimail
executable is installed atomically and Matrimail is restarted to load it.

## Slack and Google Messages

Run this on the graphical Linux laptop, not over SSH on Contabo:

```fish
nix run 'github:iniyanijoseph/nixos-config?dir=hosts/contabo#contabo-bridge-manager'
```

The launcher downloads the upstream 0.2.1 Linux x64 release with a pinned SHA256,
runs its bundled Electron inside Nix's free Steam runtime, and opens SSH
forwards to `wug@213.199.55.255`. The local listeners bind only to 127.0.0.1.
You may be prompted to verify the server's host key or authenticate SSH.
The terminal and SSH tunnel stay open until you close the application.

In the application, sign in to `https://matrix.iniyanjoseph.com` as
`@me:iniyanjoseph.com`, then manually add your own bridge URLs:

| Bridge | URL |
|---|---|
| Slack | `http://127.0.0.1:29321` |
| Google Messages | `http://127.0.0.1:29320` |

Start a fresh login in the manager, not in the Matrix bot simultaneously.
Complete CAPTCHA challenges yourself in its embedded browser. The manager
passes the resulting session back to your own bridge; no manual token/cookie
copy is required. Repeat Slack login for each workspace. Once logged in,
closing the manager does not stop bridging on Contabo.

This does not add CAPTCHA handling to the old Discord v0.7.6 bridge. A Discord
session reported as logged in should be left intact while investigating any
disconnects. Its invalid-token handler logs the specific 4004 event before
logging out. Read connection events without matching digits inside message IDs:

```fish
sudo journalctl -u mautrix-discord-native --since '24 hours ago' --no-pager -o cat \
    | rg -i 'logged out|invalid token|4004|captcha|Error connecting|Temporarily disconnected|Disconnected from Discord|User logged out|panic:' \
    | tail -n 60
```

## Matrimail history with app-password/IMAP accounts

After login is complete, send commands in your private Matrimail bot room:

```text
!matrimail status
!matrimail backfill 30 your@gmail.com
```

The second command starts a 30-day pilot, including mail already present before
the bridge was connected. To import the full retained history of the folders
selected during login, use:

```text
!matrimail backfill all your@gmail.com
```

`all` means all dates in those selected folders, not every Gmail label. Archived
mail outside INBOX is included only if an appropriate folder such as All Mail
was selected. This cannot recover old Outlook mail that has never been copied
to Gmail. Live forwarding/redirect rules do not migrate old source mail.

The worker uses a separate read-only IMAP connection and PEEK fetches, leaving
the live IDLE cursor and source flags unchanged. It freezes a UID waterline and
date window, reuses native conversion, threading, message IDs and original
dates, and saves progress after a native Matrix mapping is observed. Drafts
are skipped by the upstream processor. A mapped message is not a proof of full
attachment parity; that remains a separate acceptance check.

Progress appears in the bot room every 50 processed messages. Only one history
job runs per account. It pauses on errors or less than 5 GiB free. Repeat the
same command after interruption/restart to resume its checkpoint. A changed
UIDVALIDITY stops the import for review rather than applying old UIDs to a new
mailbox. The bot reports processed counts, including already mapped mail and
skipped drafts, not an independently audited completeness claim.

The existing OAuth-only `backlog` command is unchanged. The patched password
login also installs the folder-selection input handler after inline login and
updates the IMAP username when a corrected email address is retried.
