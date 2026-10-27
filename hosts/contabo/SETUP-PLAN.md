# Contabo self-hosted services: target state and commissioning order

This is a **target state**, not a claim that all features are available or
that one `nixos-rebuild switch` can safely log in to external accounts.

Current services remain as they are until each group below passes an
independent preflight, an offsite backup, a dry build and a rollback test.
Run `observe.fish` first and review its sanitized report.

## 1. Base operating system and recovery (running)

- Pinned Contabo-specific NixOS flake, distinct from desktop configuration.
- SSH key login; no password SSH; keep existing out-of-band VPS console access.
- Reverse-proxy HTTPS with Nginx and ACME certificates.
- PostgreSQL, Redis, Nextcloud, Synapse, existing WhatsApp bridge.
- R2-encrypted Restic backup of OS configuration, secrets, ACME keys, database
  dump, Nextcloud, Matrix, bridges and migration archives.
- Validate backup consistency and test **isolated** restoration with Synapse
  signing keys, bridge database mapping, message media and SQL dump.

**Not done merely by `restic snapshots`:** a real restore test, retention
policy review and restoration documentation.

## 2. Google Photos → Nextcloud Memories (imported; audit needed)

- Retain original Google Takeout manifest and photo duplicate quarantine.
- Validate timestamp and GPS provenance for representative older/newer
  photos, across EXIF, Google JSON and Nextcloud Memories timeline/places.
- Distinguish Files modification time from Memories capture time.
- Inspect reconciled originals and any sidecars with missing metadata.
- Only after metadata audit, recovery snapshot and explicit separate approval
  may duplicate quarantine be deleted.
- The polling migration queue no longer invokes cleanup automatically.

No re-run of Takeout metadata migration or mass EXIF rewrite until this
comparison identifies a specific defect.

## 3. Native Matrix and Discord historical cutover (not complete)

- Maintain Synapse `server_name = iniyanjoseph.com`, Cinny at
  `chat.iniyanjoseph.com` and private `@me:iniyanjoseph.com`.
- Preserve the existing Discord SQLite archive and independent collector.
- Audit scoped DMs/guild channels/threads, known inaccessible threads,
  attachment downloads and source message counts; report gaps explicitly.
- Implement a one-time bridge-native importer into **fresh portal rooms**
  using appservice timestamp massaging, oldest→newest, durable per-message
  identity mappings and idempotent retries.
- Catch up events across the import/live waterline with no gap or duplicate;
  only then enable the live Discord bridge for each portal.
- Test bidirectional messaging, reply-to-old-event, media, permissions,
  editing and deleting, encryption and recovery, then isolated restoration.
- Retire the temporary archive **after** parity and recovery are established.
  Keep the bridge's live mapping/database, which remains permanent.

The `DISCORD-IMPORT-DESIGN.md` document is a specification, not an importer.

## 4. WhatsApp (live)

- Verify link status, successful outbound/inbound messages, historical
  backfill boundaries and Matrix E2EE key recovery.
- Do not unlink/re-pair a working client merely for cleaner Nix deployment.
- Keep the encryption pickle key and appservice registration in backups.

## 5. SMS/RCS and Slack (currently disabled)

- Provision account-specific registrations, dedicated service users and
  database directories before enabling `mautrix-gmessages` or
  `mautrix-slack`.
- Confirm the bridge packages are compatible with the pinned Synapse
  version; perform independent history/backfill and live send/receive tests.
- Respect platform restrictions and do not promise complete inaccessible
  message history.
- Stage bridge activation *after* Discord archive cutover, so future bridge
  login cannot interrupt the history migration.

## 6. Email in Matrix and standard clients (currently disabled)

- Prefer the existing hosted inboxes and forwarding until DNS, MX/SPF/DKIM/
  DMARC, provider egress restrictions, abuse controls, account recovery and
  certificate/port checks are reviewed.
- Matrimail is experimental; verify its IMAP/SMTP account-specific identities,
  appservice registration, encryption/decryption and per-account reply-from
  in an isolated test before enabling.
- Stalwart is optional: do not open mail ports or claim deliverability until
  both inbound and outbound routing and abuse safeguards are verified.
- Preserve traditional IMAP/SMTP access alongside any Matrix view.

## 7. Operational supervision and notifications

- Old `matrix-command-listener` and `matrix-periodic-status` jobs were
  transient. They can be stopped on request after verifying exact unit
  identities; never stop Synapse or WhatsApp as collateral.
- `contabo.matrixMonitoring.enable = false` is safe by default. The
  opt-in module provides persistent services and a 20-minute timer if
  monitoring is explicitly desired again, *after* old transient jobs stop.
- A future `contaboctl doctor` can unify read-only probes without needing
  a long-running notification bot.
- Prefer pinned executable paths and durable, explicit one-shot migration
  tools to ambient shell PATH and background Nix shells.

## Safety gates before each future change

1. Read-only state report, with secret values and message/photo contents
   excluded.
2. Confirm repository hash/branch, NixOS lock, current active services,
   free space, filesystem state and backing data paths.
3. Confirm an **offsite** backup and rehearsed recovery.
4. Run `nix flake check` and `nixos-rebuild build`, never `switch` first.
5. Apply one service group at a time; rollback on failed health checks.
6. Verify actual user-facing send/receive and historical data, not merely
   process activity or a migration checkpoint.

### What the first `observe.fish` report cannot prove

It does not read private chat contents, authenticate external services, run
Nextcloud migrations, check live Discord account history completeness, query
private R2 backups, restore snapshots, or inspect every historical photo's GPS.
Those require separate audited tests after identifying the system's exact
state. Do **not** feed secrets back into chat.
