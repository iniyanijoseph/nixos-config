# Encrypted Contabo backups — Cloudflare R2

`contabo.backups.enable = true;` is set in Contabo's NixOS configuration.
**Before rebuilding and switching on the VPS**, create the root-only R2 credentials
and the Restic encryption password described below. The service has not been
proven functional until a snapshot and restore test succeed.

## Set up R2

In the Cloudflare dashboard, create a private Standard-class R2 bucket named
`contabo-encrypted-backups`. Create a **bucket-scoped** R2 API token with
Object Read & Write permissions and save the Access Key ID / Secret Access Key
in a password manager. Find your Cloudflare R2 account ID in the dashboard.

On the VPS (do not commit or paste secrets into chat):

```sh
sudo install -d -m 0700 -o root -g root /var/lib/secrets
sudo sh -c 'umask 077; openssl rand -base64 48 > /var/lib/secrets/restic-password'
```

**Store a second copy of the restic encryption password offline.** If lost,
the backup is permanently unreadable even with working R2 credentials.

As root, create `/var/lib/secrets/restic-r2.env` containing:

```ini
RESTIC_REPOSITORY=s3:https://<ACCOUNT_ID>.r2.cloudflarestorage.com/contabo-encrypted-backups
AWS_ACCESS_KEY_ID=<R2_ACCESS_KEY_ID>
AWS_SECRET_ACCESS_KEY=<R2_SECRET_ACCESS_KEY>
AWS_DEFAULT_REGION=auto
```

Replace placeholders with your private values. Then:

```sh
sudo chown root:root /var/lib/secrets/restic-r2.env /var/lib/secrets/restic-password
sudo chmod 600 /var/lib/secrets/restic-r2.env /var/lib/secrets/restic-password
```

## Enable, run, and verify

Once the files exist and have permissions `0600`, deploy the committed
configuration on Contabo. **Also update the server's lock file for the
2026-10-21 PHP security patch** before switching; the old pinned lock file
still targets vulnerable PHP 8.4.26. Stop if the evaluated PHP version isn't
at least 8.4.27.

```sh
cd /etc/nixos
sudo git pull --ff-only
cd hosts/contabo
sudo nix flake update nixpkgs
sudo nix eval --raw '.#nixosConfigurations.contabo.config.services.nextcloud.phpPackage.version'
# Expected PHP 8.4.27; stop if older.
sudo nixos-rebuild build --flake .#contabo
sudo nixos-rebuild switch --flake .#contabo
sudo systemctl start restic-backups-contabo.service
sudo journalctl -u restic-backups-contabo.service -n 60 --no-pager
sudo restic-contabo snapshots
sudo restic-contabo check
```

The first backup can take some time. The automated timer runs once daily,
retaining 7 daily, 4 weekly, 6 monthly and 2 yearly snapshots.

The job backs up Nextcloud files/configuration, a temporary logical dump of
*all PostgreSQL databases and roles*, TLS keys, local server secrets,
SSH host keys, and this NixOS Git checkout. Nextcloud preview caches are
excluded; they can be regenerated.

### Test a partial restore (never over production)

```sh
sudo install -d -m 0700 -o root -g root /var/lib/restic-restore-test
sudo restic-contabo restore latest --target /var/lib/restic-restore-test \
  --include /var/lib/restic-staging/postgres-all.sql
sudo test -s /var/lib/restic-restore-test/var/lib/restic-staging/postgres-all.sql
```

This verifies the SQL dump can be recovered, not full application recovery.
Keep an offline copy of the backup password and R2 credentials and eventually
practice restoring a test Nextcloud instance on a separate machine.

### Limitations

Nextcloud's file tree is backed up *live*, while PostgreSQL is dumped at a
single point in time. This is not a fully atomic snapshot across the database
and files; for stronger consistency, use a temporary maintenance window or an
OS filesystem snapshot during the backup. Retain Google originals until
recovery has been tested.

**Matrix is not covered yet.** Later, add Synapse media, config and signing
keys. The PostgreSQL dump will automatically include any Synapse database.
