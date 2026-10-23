# One-time Discord → native Matrix history: migration design

**Status: design only. Not implemented, deployed or authorized to write Matrix
events.** The current collector saves scoped Discord message JSON in
`/var/lib/discord-archive/archive.sqlite`; the current live Discord bridge
is disabled. Do not use this document as a run command.

## Desired steady state

- Synapse stores **ordinary Matrix events** for the available Discord history.
  No custom client, archive viewer, Synapse database patch, or permanent
  SQLite history mirror is needed.
- The live Discord bridge owns the portal, user and message mappings for those
  events and continues delivering new messages to the same rooms.
- The historical importer is removable after audited import and restore.
- The **bridge mapping database stays**: it is needed for replies, edits,
  deduplication and portal identity, even when the original archive is gone.
- Historical Discord content is not trusted: sanitize formatting, filenames,
  URLs, mentions, and event metadata during conversion.

## Sources and scope

Current collection scope is DMs plus guild `804408079940583475` and discovered
threads, **not every Discord server**. A currently blocked active-thread
discovery request may leave incomplete history. Old closed/unlisted DMs,
deleted messages, edit history, ephemeral media and messages in channels
without access may be irrecoverable.

An importer MUST produce a provenance inventory first:

1. Enumerate all discovered channels, completeness flags and scope failures.
2. Count and fingerprint message IDs per channel.
3. Enumerate all referenced attachments and classify downloaded, inaccessible,
   unsupported and intentionally skipped media.
4. Record every missing source channel/message as a coverage limitation; never
   claim to have recovered the unknowable.

## Supported Matrix insertion method

Use the **application-service** send API with the supported `ts` parameter
(timestamp massaging). This creates native Matrix events with historical
timestamps; it **does not insert them earlier in the event DAG**. For an
ordered, natural timeline, start with fresh bridge-managed empty portal rooms,
then insert source messages **oldest to newest** before enabling normal live
delivery for that portal.

Upstream references:
- https://spec.matrix.org/latest/application-service-api/#timestamp-massaging
- https://docs.mau.fi/bridges/general/backfill.html

Do not write into Synapse PostgreSQL tables directly, synthesize event IDs,
or attempt to rewrite pre-existing room timelines. The migration must use
the bridge's existing room/message conversion and mapping model; do not
guess which database tables or internal functions exist until examining the
exact pinned bridge version and migration APIs.

## Import state machine (per Discord conversation)

```
DISCOVERED → SNAPSHOTTED → PORTAL_READY → REPLAYING → CATCHING_UP
    → LIVE → AUDITED
```

- SNAPSHOTTED freezes a waterline: last source Discord message ID and source
  coverage data. Discord message IDs are snowflakes, not contiguous counts.
- PORTAL_READY means only the bridge owns the room and ghost identities.
- REPLAYING imports source events in stable (timestamp, snowflake) order;
  the bridge's mapping is authoritative.
- CATCHING_UP accounts for all newer source events since that waterline,
  using a durable buffer or an explicitly verified gap-free poll. The
  importer must not race with live delivery into the same portal.
- LIVE begins only when the gap is reconciled and bidirectional send/receive
  tests pass, including a reply to an imported message.
- AUDITED means the portal and its media/mappings are verified and restorable.

No automatic cutover when an API scope has incomplete discovery, unresolved
source IDs, lost attachment contents, or unexpected mapping collisions.

## Idempotency and failure handling

- Identity key: `(discord_channel_id, discord_message_id)`.
- Durable mapping: `(discord_channel_id, discord_message_id)` →
  `(matrix_room_id, matrix_event_id)`, owned by the live bridge.
- Use stable Matrix transaction IDs for retransmissions if the bridge API
  supports them. On ambiguous send timeout, **reconcile the bridge's mapping**
  before retrying; never blindly replay.
- Store per-portal checkpoints only after a Matrix send and mapping commit.
- On mismatch between an already-imported Matrix event and archived content,
  stop and require review; never overwrite or silently duplicate an event.
- Track failed media independently from successful text import.
- Respect Matrix client semantics: replies, reactions, media, threads,
  author identities, edits and redactions. Only construct relations that
  are backed by actual source evidence.

## Authentication, encryption, durability

Choose bridge-native ghost identities and whether to enable double puppeting
**before creating portal rooms**. A puppet must not arbitrarily impersonate
another person's Matrix account.

Choose room encryption and device-key recovery before importing hundreds of
thousands of events. Backup Synapse signing keys, media, database, appservice
registration and live bridge database as one **tested recoverable set**.
Plaintext in the Discord archive is sensitive; keep it private and backed up
until archive retirement.

Matrix historical timestamps are metadata, not proof events cryptographically
existed in Matrix at the source dates.

## Preflight, rollout and acceptance

1. Confirm original SQLite archive is intact and cold-backup recoverable.
2. Test **one small DM** in a fresh bridge-owned portal in an isolated
   environment; verify chronology in Cinny and in raw Matrix events.
3. Test replies to old events, authorship, attachments, deletion/edit handling,
   server restart, importer restart and replay after ambiguous timeout.
4. Test a larger guild channel, then full source scope with bounded workers.
5. Verify every accessible source message maps to exactly one Matrix event,
   plus explicit records for anything skipped or unavailable.
6. Verify live send/receive after cutover and continued operation across a
   bridge restart and a Synapse restart.
7. Perform an **isolated recovery** of PostgreSQL, media, signing keys,
   encryption state and the bridge mapping DB; verify imported history and
   subsequent live replies from a Matrix client.
8. Only then write a durable `discord-native-import-verified.json` marker
   with audited scope, message totals, exclusions, backup reference and time.

Manual archive retirement comes **after** all acceptance gates. Retire the
unneeded *local duplicate archive* and its archival job explicitly; do not
delete bridge mappings or prematurely prune R2 recovery snapshots.

## NixOS integration boundaries

- Package a fixed bridge version, migration adapter and its dependencies
  through the **Contabo flake**. Avoid ad hoc unpinned `nix shell` lookups.
- Put portal/bridge database location, systemd identity, hardening, secret
  provisioning interface and live service into a dedicated Discord module.
- Define importer as a **one-time opt-in service** with bounded resources;
  no `WantedBy=multi-user.target` for destructive/import work.
- Define explicit import and cutover commands with `--dry-run` and
  independent read-only preflight. Do not make `nixos-rebuild switch`
  automatically start migration or delete anything.
- Restic must cover `/var/lib/mautrix-discord` whenever live bridging is
  enabled, in addition to Synapse, PostgreSQL dumps, credentials and media.
- Leave migration-specific code under an archived `migrations/` location
  after success. The steady-state configuration should not depend on it.

**Not a claim of completeness:** the official Discord user-data export can
supplement coverage evidence for an account's own messages but cannot
reconstruct other participants' deleted or inaccessible content.
