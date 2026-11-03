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

## Retrospective consolidation of pre-existing email rooms

On first connection with the patched Matrimail service, a checkpointed,
low-rate background worker detects old per-subject `thread:` portals and
automatically replays **all retained messages in the account's selected IMAP
folders** into the newer contact-based portals. There is no need to issue the
manual `backfill all` command to start this migration. Backfill uses its
existing read-only IMAP connection, 2 messages/second limit, 5 GiB disk guard,
and UIDVALIDITY validation. Restarting the service resumes the saved
per-folder checkpoint. If an IMAP login is unavailable, the old rooms are
preserved until you reconnect the account.

When replay finishes, the bridge audits the original per-subject portals
against the new contact-room native message mappings **including message
parts**, within the same email account. A legacy room is marked
`Archived email · …` and given links to the new contact rooms only if all
its identifiable old email messages/parts have real destination mappings.
Custom room names are left unchanged. Any unverified old rooms are retained
unchanged; a successfully marked room is **not deleted, forgotten, or
force-left** and keeps its original Matrix history. The bridge cannot
literally move Matrix events between rooms or promise attachment parity
merely from native mappings.

If old rooms are not archived, check whether the account's IMAP selected
folders include the historical mail (for Gmail, this usually requires
the All Mail folder). Read the Matrimail journal for
`Contact-room replay`, `Legacy email`, or `unverified_rooms`. A manual
`!matrimail backfill all your@gmail.com` completes the same coverage audit
and posts the result into the bot DM. Out-of-scope, deleted, or no-longer-
available source emails require a separate recovery strategy; the worker
does not invent their content or modify the originals.

## Contact rooms and email replies

The pinned Matrimail patch enables one contact room per monitored account and
external address. Separate subjects appear as native Matrix threads. Incoming
chains stay anchored to their original contact even when participants change;
sent-first multi-recipient conversations use a separate recipient-set room.

Reply inside a thread (or explicitly reply to an email) to retain that chain's
subject, recipients and RFC email headers. Normal replies are reply-all;
`!matrimail reply-only` applies to the next send only. A top-level message starts
a new email to the contact, with its first line as the subject. For an explicit
subject/CC, use `!matrimail compose to:alice@example.com subject:"Hello"` in the
bot DM, then reply in the draft's Matrix thread. Creating the draft sends no mail.

The room repair worker fixes the old PL-101 posting restriction for both
`m.room.message` and `m.room.encrypted`. It accepts existing pending invitations
only in native Matrimail portals owned by the account. It respects explicit
leaves and bans. The registration delegates exactly `@me:iniyanjoseph.com` to
Matrimail's normal appservice double puppet; no wildcard human namespace or
other users' accounts are delegated. As with any double puppet, Matrimail is
trusted to act as that Matrix account. Tokens remain in private server files.
One Synapse restart loads that changed registration; other active bridges are
preserved. New rooms auto-join through the normal double puppet.

To check the new layout manually or resume a paused import, run a pilot in the Matrimail bot DM:

```text
!matrimail backfill 30 your@gmail.com
```

Then `!matrimail backfill all your@gmail.com` covers all retained mail in the
folders selected during login. The contact layout uses separate remote IDs and
`contabo-backfill-contacts-v2` checkpoints, so an old completed import cannot
silently skip the migration. Existing legacy rooms/events are preserved; Matrix
cannot move their events into new rooms. Repeated commands resume and deduplicate
within the contact layout. Mail outside the selected folders or absent from
Gmail is not imported. No account logout is required for this update.
