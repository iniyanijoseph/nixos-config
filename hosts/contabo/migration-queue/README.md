# Contabo deferred migration: Discord archive → Google Photos → bridge preflight

**This is an explicit one-shot queue, not a NixOS timer.** It can be
started *now*, via a detached transient systemd service, without a
`nixos-rebuild switch`. Nothing is scheduled merely by cloning/pulling
the repository. It records progress and is safe to rerun after failure.

The dependency graph is:

```text
A complete local Takeout SHA-256 manifest exists on Contabo
          +
All canonical uploaded files + Google JSON match Takeout SHA-256
          +
Extra misnested files are verified against their original manifest paths
          +
Entire tree stays unchanged for 1 hour (no upload activity)
          |
          v
Fresh encrypted restic-backups-contabo snapshot (must succeed)
          |
          v
Recover verified missing canonical files (no overwrite), quarantine exact duplicates, refresh Nextcloud file cache
          |
          v
Re-verify canonical Takeout directory exactly
          +
Discord collector has stopped AND SQLite discovery/history checkpoints are clean
          |
          v
Nextcloud Memories: migrate Google Takeout JSON metadata to EXIF
          |
          v
Memories: reindex the Google Photos directory (must succeed)
          |
          v
Evaluate NixOS Stalwart, Matrimail, SMS/RCS, Slack future profiles;
run read-only mail DNS/port preflight
          |
          v
Write "services-staged.json" for MANUAL review and later activation
```

**Photo verification and safe duplicate repair run while Discord is still
collecting. Only metadata migration, Memories indexing, and future service
evaluations wait for the Discord completion gate.**

**No NixOS switch, bridge login, DNS/MX change, mail service start,
or message sending happens in this workflow.** Those steps require
mail passwords, DNS and external deliverability checks, Google Messages
device pairing, and separate Slack workspace logins.

## Stage 1 — Pull repo on Contabo (safe while Discord collects)

```fish
cd /etc/nixos
sudo git pull --ff-only
```

No `nixos-rebuild switch`. Python scripts run from checkout.

## Stage 2 — Make a cryptographic manifest of the *original* Takeout

The Nextcloud web upload does **not** provide an authoritative server-side
"completed" event that this script can rely on. So, on your **LOCAL**
computer (where the original extracted Takeout still exists):

```fish
scp wug@213.199.55.255:/etc/nixos/hosts/contabo/migration-queue.py \
    ~/migration-queue.py

nix shell nixpkgs#python3 --command python3 \
    ~/migration-queue.py manifest \
    "$HOME/Pictures/Takeout/Google Photos" \
    "$HOME/photos-manifest.json"
```

Adjust the local folder if necessary. The manifest contains the relative
path, byte length and SHA-256 hash of **every** file, including Google's
JSON metadata. It does not contain the file contents. Do NOT erase
your local Takeout ZIPs or folder yet.

Upload only the manifest to Contabo (still from local computer):

```fish
scp ~/photos-manifest.json wug@213.199.55.255:~/
```

Back in the **Contabo** SSH session:

```fish
sudo install -d -m 0700 /var/lib/migration-queue
sudo install -m 0600 -o root -g root \
    ~/photos-manifest.json \
    /var/lib/migration-queue/photos-manifest.json
```

The queue checks the actual Nextcloud files in
`<datadirectory>/wug/files/Photos/Google Photos` (the Nextcloud data
directory is discovered through `nextcloud-occ`). If the drag/drop
uploaded a different destination, update `FOLDER` in
`migration-queue.py` and ensure the manifest matches the real contents.
File counts and checksums must match exactly for the canonical files.
The reconciliation helper recognizes only files accidentally nested under
`Photos from 2016` that exactly match their original Takeout manifest.
If a canonical file is missing, the verified misplaced copy can be
relocated to its proper original location **without overwriting anything**.
If the canonical copy already exists and matches, the misplaced extra
is moved to a private quarantine. Everything else blocks the queue;
it never guesses, silently merges mismatched files or overwrites a file.

While Firefox is still uploading, the queue checks names and sizes
without repeatedly hashing gigabytes of already-uploaded photos.
Once all original files are accounted for, a complete SHA-256
verification **starts a one-hour quiescence timer**. All file
paths, byte sizes, modification times and inode identities must remain
unchanged for that whole interval. Only after the interval and a second
unchanged audit does the queue start an encrypted Restic backup. It then
recovers hash-matched missing files at their canonical paths and moves
verified redundant copies into
`/var/lib/migration-queue/photos-duplicate-quarantine/`
rather than permanently deleting them, and runs
`nextcloud-occ files:scan --path=/wug/files/Photos/Google Photos`
to refresh Nextcloud's database.

If an expected file is missing **both** from its canonical location and
from the known misplaced prefix, still uploading, corrupted, or
unexpectedly different, **nothing is moved** and the queue keeps
waiting. A permanently missing or mismatched file requires manual
review, not an automatic overwrite. Empty extra folders may remain after cleanup;
they can be removed later in Nextcloud Files once all indexing passes.

## Stage 3 — Start (or update) the queue detached, without switching NixOS

If you already started `discord-photos-queue`, the running Python process
will not automatically reload source changes after `git pull`. **Restart
only the queue service**, not Discord, NixOS or Synapse:

```fish
cd /etc/nixos
sudo git pull --ff-only
nix shell nixpkgs#python3 --command python3 -m unittest   hosts/contabo/test_migration_queue.py -v
sudo systemctl restart discord-photos-queue
```

This preserves existing checkpoint files, the local Takeout upload,
the Discord collector and the Nextcloud browser session. Review
`journalctl -u discord-photos-queue` afterward. If the unit doesn't
exist, use the initial `systemd-run` command below.

On **Contabo**:

```fish
cd /etc/nixos

sudo systemd-run \
    --unit=discord-photos-queue \
    --description="Wait for verified Discord/Takeout, then migrate photos" \
    --property=Restart=on-failure \
    --property=RestartSec=300s \
    /run/current-system/sw/bin/nix shell nixpkgs#python3 --command python3 \
    /etc/nixos/hosts/contabo/migration-queue.py run --interval 600
```

It is a **transient systemd service**, not tied to SSH or tmux.
Closing SSH won't stop it. It will recheck conditions every 10 minutes.
A failed migration or backup restarts after five minutes; completed steps
are marked so they won't be repeated unnecessarily.

**A server reboot removes transient systemd units.** Re-run the
`systemd-run` command after reboot; the SQLite archive, Takeout
manifest, and migration checkpoint files persist. Do not launch a second
instance while one is already running.

Check progress:

```fish
systemctl status discord-photos-queue
sudo journalctl -u discord-photos-queue -n 60 --no-pager

sudo nix shell nixpkgs#python3 --command python3 \
    /etc/nixos/hosts/contabo/migration-queue.py status
```

Stop the monitor WITHOUT deleting progress:

```fish
sudo systemctl stop discord-photos-queue
```

## Discord may never pass automatically

Your current collector encounters inaccessible/unsupported API endpoints,
including "Only bots can use this endpoint". Its history report may
remain incomplete even after the process exits. **This queue will
deliberately wait indefinitely** in that case rather than mistake a
failed export for completion. This is a safety safeguard, not a broken
timer. Review `collector.py verify` and its error report; decide
separately whether a partial archive is acceptable. There is **no**
silent success or automatic completeness override.

If Discord's blocked endpoints remain impossible to collect, and you
**explicitly accept** incomplete history, you can release this gate
only **after the collector is no longer running**:

```fish
sudo nix shell nixpkgs#python3 --command python3   /etc/nixos/hosts/contabo/migration-queue.py   approve-partial-discord   --reason "Discord API blocks unsupported channels and thread discovery"
```

The command requires typing `ACCEPT INCOMPLETE DISCORD`. It writes a
private, auditable `discord-partial-approved.json`; no old messages are
deleted. The queue will then proceed with Photos if its manifest matches.
This does **not** magically restore missing Discord data. To revoke
approval before migration, stop the queue and delete just that marker.

Even a passing collector verification only means all **registered,
discoverable** channels were exhausted. Old DMs absent from Discord's
API listings could still be missing.

## Photos migration is destructive to metadata

Memories' `memories:migrate-google-takeout` edits the uploaded photos.
The queue starts an encrypted Restic backup *before duplicate cleanup*
and again before EXIF migration. Failure stops the workflow. All 13GB+ of Takeout originals should still be kept
on your local machine until the results are audited.

Checkpoint files and quarantined duplicates are under
`/var/lib/migration-queue/`. Do not delete the quarantine or old
Restic snapshots until the final Takeout verification and Memories
indexing are audited. The original exported Takeout remains the
best independent recovery source.
If the index fails after EXIF migration, restarting only re-runs indexing.
If the preflight evaluation fails, the queue records an error and retries;
it **does not** enable a mail or chat bridge.

## When the queue completes

- `photos-reconciled.json` indicates complete upload verification,
  one-hour quiescence and optional safe duplicate quarantine.
- `photos-migrated.json` and `photos-indexed.json` indicate the
  metadata update and Memories index steps were successful.
- `services-staged.json` indicates the future NixOS profiles passed
  **evaluation**, not that anything was deployed.
- `service-readiness.log` contains read-only mail preflight and Nix
  evaluation details.

After reviewing status and with Discord no longer downloading, use
`mail-server/README.md` and `bridges-extra/README.md` to activate
each service with the required local secrets and account pairings.
Do not change the domain's MX records until Stalwart inbound/outbound
mail delivery is proved. Full Slack/SMS history is not guaranteed on
ordinary Synapse; historical imports should be planned before first room
creation.

Tests:

```fish
nix shell nixpkgs#python3 --command python3 -m unittest \
    hosts/contabo/test_migration_queue.py -v
```

## October 22: content-hash recovery of scrambled Google Photos

The folder-based upload has misplaced files across different albums, not
just below `Photos from 2016`. The new
`migration-queue/hash-recovery.py` uses original SHA-256 content and sizes
to restore files to every original manifest path, creating **independent**
copies (not hardlinks) so Memories' EXIF edits cannot affect other albums.
Files beyond the manifest are quarantined, not deleted. A successful
Restic snapshot and a one-hour unchanged-file verification are required
before any recovery operation.

**Incomplete exports remain blocked.** Run:

```fish
cd /etc/nixos
sudo nix shell nixpkgs#python3 --command python3 \
  hosts/contabo/migration-queue/export-missing.py
```

This prints the missing counts and saves **every** absent Takeout path
to `/var/lib/migration-queue/photos-missing.txt`, with a full read-only
recovery plan at `photos-recovery-plan.json`. Use this list against the
**original local Google Takeout export** to selectively upload only truly
missing files; do not invent supplemental JSON metadata for older photos.
If an original manifest entry lists a JSON sidecar, however, that exact
file is needed for a complete verified import. Do not modify or delete
the original Takeout and don't run metadata migration early.

After selectively uploading missing files through Nextcloud Files,
restart only the transient queue (no switch or Discord interruption):

```fish
sudo systemctl restart discord-photos-queue
```

The queue will automatically rehash and recover verified files once all
manifest content exists. No automatic network uploads are performed
by the queue. Verify all paths and backup space before proceeding.
