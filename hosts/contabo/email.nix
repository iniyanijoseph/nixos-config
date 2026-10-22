# Experimental Matrix <-> IMAP/SMTP bridge (Matrimail).
# The service is opt-in; see email-bridge/README.md before enabling it.
{ config, lib, ... }:
let
  cfg = config.contabo.emailBridge;
in
{
  options.contabo.emailBridge.enable = lib.mkEnableOption
    "experimental Matrimail bridge to existing email inboxes";

  config = lib.mkMerge [
    # Safe staging: provision a dedicated user/directory while disabled.
    {
      users.groups.matrimail = { };
      users.users.matrimail = {
        isSystemUser = true;
        group = "matrimail";
        home = "/var/lib/matrimail";
        description = "Matrimail Matrix/email bridge";
      };
      systemd.tmpfiles.rules = [
        "d /var/lib/matrimail 0750 matrimail matrimail -"
      ];
    }

    (lib.mkIf cfg.enable {
      # Generate registration.yaml with the bridge CLI before enabling.
      # It must remain unreadable by other users.
      services.matrix-synapse.settings.app_service_config_files = [
        "/var/lib/matrimail/registration.yaml"
      ];
      systemd.services.matrix-synapse.serviceConfig.SupplementaryGroups = [
        "matrimail"
      ];

      systemd.services.matrimail = {
        description = "Matrimail experimental Matrix email bridge";
        wantedBy = [ "multi-user.target" ];
        requires = [ "matrix-synapse.service" ];
        after = [ "matrix-synapse.service" "network-online.target" ];
        wants = [ "network-online.target" ];
        serviceConfig = {
          User = "matrimail";
          Group = "matrimail";
          WorkingDirectory = "/var/lib/matrimail";
          ExecStart = "/var/lib/matrimail/bin/matrimail --config /var/lib/matrimail/config.yaml";
          EnvironmentFile = "/var/lib/secrets/matrimail.env";
          Restart = "on-failure";
          RestartSec = "15s";
          UMask = "0077";
          NoNewPrivileges = true;
          PrivateTmp = true;
          ProtectSystem = "strict";
          ProtectHome = true;
          ReadWritePaths = [ "/var/lib/matrimail" ];
          RestrictAddressFamilies = [ "AF_INET" "AF_INET6" "AF_UNIX" ];
        };
      };
    })
  ];
}
