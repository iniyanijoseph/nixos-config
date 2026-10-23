{ config, lib, pkgs, ... }:
{
  # Does not start a backup service until R2 credentials and the restic
  # encryption password have been installed locally (outside Git).
  options.contabo.backups.enable = lib.mkEnableOption
    "encrypted offsite backups of Contabo and Nextcloud to Cloudflare R2";

  config = lib.mkIf config.contabo.backups.enable {
    services.restic.backups.contabo = {
      environmentFile = "/var/lib/secrets/restic-r2.env";
      passwordFile = "/var/lib/secrets/restic-password";
      initialize = true;

      # Create a PostgreSQL logical backup; never copy the live DB directory.
      backupPrepareCommand = ''#!${pkgs.runtimeShell}
        set -eu
        umask 077
        ${pkgs.coreutils}/bin/install -d -m 0700 /var/lib/restic-staging
        ${pkgs.util-linux}/bin/runuser -u postgres -- \
          ${config.services.postgresql.package}/bin/pg_dumpall \
          > /var/lib/restic-staging/postgres-all.sql
      '';
      backupCleanupCommand = ''#!${pkgs.runtimeShell}
        ${pkgs.coreutils}/bin/rm -f /var/lib/restic-staging/postgres-all.sql
      '';

      paths = [
        "/var/lib/nextcloud"
        "/var/lib/matrix-synapse"
        "/var/lib/mautrix-whatsapp"
        "/var/lib/discord-archive"
        "/var/lib/migration-queue"
        "/var/lib/restic-staging/postgres-all.sql"
        "/var/lib/secrets"
        "/var/lib/acme"
        "/etc/ssh"
        "/etc/nixos"
      ]
      # Future live Discord bridge mapping/authentication is NOT redundant
      # with Matrix history. Back it up whenever the bridge is enabled.
      ++ lib.optionals config.services.mautrix-discord.enable [ "/var/lib/mautrix-discord" ]
      ++ lib.optionals config.contabo.mail.enable [ "/var/lib/stalwart" ]
      ++ lib.optionals config.contabo.emailBridge.enable [ "/var/lib/matrimail" ]
      ++ lib.optionals config.contabo.messagingBridges.sms.enable [ "/var/lib/mautrix-gmessages" ]
      ++ lib.optionals config.contabo.messagingBridges.slack.enable [ "/var/lib/mautrix-slack" ];
      exclude = [ "**/appdata_*/preview/**" ];
      pruneOpts = [
        "--keep-daily 7"
        "--keep-weekly 4"
        "--keep-monthly 6"
        "--keep-yearly 2"
      ];
      timerConfig = {
        OnCalendar = "daily";
        RandomizedDelaySec = "1h";
        Persistent = true;
      };
    };
  };
}
