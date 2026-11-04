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

On startup of each configured email account, a checkpointed, low-rate
worker detects legacy per-subject `thread:` portals and attempts to replay
all retained messages in the account's selected IMAP folders into contact
rooms. It connects with a **separate read-only IMAP session**; it no longer
waits for live IMAP IDLE to finish. Missing IMAP credentials, concurrent
backfills and other early exits are reported in the private Matrimail journal
instead of silently doing nothing. Replay uses a two-messages/second limit,
a 5 GiB free-space guard, UIDVALIDITY checks and durable folder checkpoints.
A manual `!matrimail backfill all <email>` remains available to resume.

A deployment alone cannot manufacture historical emails that no longer exist
in those IMAP folders. If you have only a new Stalwart mailbox forwarding
recent mail, the original old Matrix rooms may contain content absent from
the current IMAP source; that requires a separate Matrix-event recovery
procedure rather than another IMAP retry.

To diagnose exactly what happened, use the **read-only** status command on
Contabo:

```fish
sudo contabo-admin mail-consolidation
sudo journalctl -u matrimail --since '2026-11-03 18:00' --no-pager -o cat \
  | rg 'Email consolidation|Contact-room migration|Legacy email room|Starting independent IMAP replay'
```

The first command reports routing state, registered account/login counts,
old and new room counts, mapping completeness, retirement markers and
checkpoint counts, without printing email addresses, subjects, bodies or
credentials. It does not verify live Matrix permissions or actual mailbox
history. Do not delete old rooms based on mapping counts alone.

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

The pinned Matrimail patch creates direct rooms for one-to-one exchanges and
**group email rooms** for multi-person exchanges. The initial external
participants (From, To, Cc, excluding your own configured aliases) determine
the room, with addresses canonicalized, deduplicated and sorted. For example,
an Alice/Bob/you conversation stays in an Alice+Bob group room whether Alice
or Bob responds. A subsequent direct reply in the same chain remains in that
room; a separate direct email with Alice goes into Alice's one-to-one room.
Different subjects in a room become separate native Matrix threads.

The original room association is frozen for each already-recognized chain,
even if a fourth person joins or one person is later omitted. This prevents
replies from jumping between rooms. Outbound reply-all follows the selected
message's latest To/Cc, **not** the entire historical room membership.
Some previously imported emails already have older native room mappings;
changing routing does **not** silently move those Matrix events. A later
isolated rebuild would be necessary to reconstruct misgrouped existing
`contact:` rooms.

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

## Removing superseded email rooms

First complete the retained IMAP import and inspect the private journal
for a blocked UID if it pauses:

```fish
sudo journalctl -u matrimail --since '24 hours ago' --no-pager -o cat \
  | rg -i 'history stopped at mailbox|history import paused|history scan|contact.room'
sudo contabo-admin mail-consolidation
```

When the native mapping audit has verified the old message parts and the
historical import checkpoints are complete, preview owner-scoped, superseded
`thread:` rooms without modifying anything:

```fish
sudo contabo-admin mail-prune-legacy
```

Only after a verified, fresh R2 snapshot, run this explicit operation:

```fish
sudo contabo-admin mail-prune-legacy --apply --limit 25
```

This calls Synapse's **asynchronous** v2 room-deletion API. It deletes
only retired legacy Matrimail portals that belong to the owner's login,
with confirmed replacement message-part mappings. The private ledger
records accepted deletion IDs and prevents duplicate submissions.
Synapse deletion itself must be checked separately; submission is not
proof of completed purging.

Deleting a room purges its Matrix events, so neither the launcher nor
`!matrimail backfill all` executes this operation automatically. Incomplete
checkpoints, missing destination mappings, absent account authentication,
and old rooms belonging to other accounts remain protected. This operation
does not remove already-misgrouped newer `contact:` rooms, and does not
reset credentials or the native mapping database. A wholesale clean import
requires a distinct, backed-up versioned rebuild before old contact rooms
can be safely purged.
