# Contabo deferred migration: Discord archive → Google Photos → bridge preflight

**This is an explicit one-shot queue, not a NixOS timer.** It can be
started *now*, via a detached transient systemd service, without a
`nixos-rebuild switch`. Nothing is scheduled merely by cloning/pulling
the repository. It records progress and is safe to rerun after failure.

The dependency graph is:

```text
Discord collector process stopped
          +
Discord SQLite scan/refresh checkpoints all clean (0 incomplete)
          +
A complete local Takeout SHA-256 manifest exists on Contabo
          +
Every uploaded Nextcloud file matches that manifest exactly
          |
          v
Fresh encrypted restic-backups-contabo snapshot (must succeed)
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
File counts and checksums must match exactly. Only **then** is the upload
considered finished.

## Stage 3 — Start the queue detached, without switching NixOS

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
The queue starts an encrypted Restic backup *before* migration. Failure
stops the workflow. All 13GB+ of Takeout originals should still be kept
on your local machine until the results are audited.

Checkpoint files are under `/var/lib/migration-queue/`.
If the index fails after EXIF migration, restarting only re-runs indexing.
If the preflight evaluation fails, the queue records an error and retries;
it **does not** enable a mail or chat bridge.

## When the queue completes

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
