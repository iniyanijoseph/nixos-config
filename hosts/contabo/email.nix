# Experimental Matrix <-> IMAP/SMTP bridge (Matrimail).
# Opt-in only. The binary and generated registration must be provisioned first
# as described in email-bridge/README.md. This file never stores mail secrets.
{ config, lib, ... }:
let
  cfg = config.contabo.emailBridge;
in
{
  options.contabo.emailBridge.enable = lib.mkEnableOption
    "experimental Matrimail bridge to existing email inboxes";

  config = lib.mkIf cfg.enable {
    users.groups.matrimail = { };
    users.users.matrimail = {
      isSystemUser = true;
      group = "matrimail";
      home = "/var/lib/matrimail";
      description = "Matrimail Matrix/email bridge";
    };

    systemd.tmpfiles.rules = [
      "d /var/lib/matrimail 0700 matrimail matrimail -"
    ];

    # The registration file is created locally with the bridge's own CLI.
    # DO NOT enable before provisioning it. Synapse must read this file at
    # startup; this group grants access without world-readable tokens.
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
  };
}
