# Opt-in SMS/RCS and Slack Matrix bridges.
# BOTH are disabled by default. No accounts, secrets, or registrations
# are created during a normal NixOS switch.
{ config, lib, pkgs, ... }:
let
  cfg = config.contabo.messagingBridges;
  packages = import ./bridges-extra-pkgs.nix { inherit pkgs; };
  bridge = {
    gmessages = {
      enable = cfg.sms.enable;
      name = "mautrix-gmessages";
      package = packages.gmessages;
      port = 29320;
    };
    slack = {
      enable = cfg.slack.enable;
      name = "mautrix-slack";
      package = packages.slack;
      port = 29321;
    };
  };
  enabled = lib.filterAttrs (_: b: b.enable) bridge;
  mkService = b: {
    description = "${b.name} Matrix bridge (manually provisioned)";
    wantedBy = [ "multi-user.target" ];
    after = [ "matrix-synapse.service" "network-online.target" ];
    requires = [ "matrix-synapse.service" ];
    wants = [ "network-online.target" ];
    serviceConfig = {
      Type = "simple";
      User = b.name;
      Group = b.name;
      WorkingDirectory = "/var/lib/${b.name}";
      ExecStart = "${lib.getExe b.package} --config /var/lib/${b.name}/config.yaml";
      Restart = "on-failure";
      RestartSec = "20s";
      UMask = "0027";
      NoNewPrivileges = true;
      ProtectHome = true;
      ProtectSystem = "strict";
      ReadWritePaths = [ "/var/lib/${b.name}" ];
      PrivateTmp = true;
    };
  };
in {
  options.contabo.messagingBridges = {
    sms.enable = lib.mkEnableOption "mautrix-gmessages SMS/RCS integration";
    slack.enable = lib.mkEnableOption "mautrix-slack integration";
  };

  config = lib.mkMerge [
    # Create service identities during ordinary future NixOS staging, so
    # registrations can be provisioned before either bridge is enabled.
    {
      users.groups = lib.mapAttrs' (_: b: lib.nameValuePair b.name {}) bridge;
      users.users = lib.mapAttrs' (_: b: lib.nameValuePair b.name {
        isSystemUser = true;
        group = b.name;
        home = "/var/lib/${b.name}";
      }) bridge;
      systemd.tmpfiles.rules = lib.mapAttrsToList (_: b:
        "d /var/lib/${b.name} 0750 ${b.name} ${b.name} -") bridge;
    }

    (lib.mkIf (enabled != { }) {
    # Staged configuration relies on locally generated config.yaml and
    # registration.yaml; do not enable before provisioning both.
    # Synapse needs to read private registrations without world-readable
    # appservice tokens. Bridge user groups are restricted to each bridge.
    systemd.services = {
      matrix-synapse.serviceConfig.SupplementaryGroups =
        lib.mapAttrsToList (_: b: b.name) enabled;
    } // (lib.mapAttrs' (_: b:
      lib.nameValuePair b.name (mkService b)) enabled);
    services.matrix-synapse.settings.app_service_config_files =
      lib.mapAttrsToList (_: b: "/var/lib/${b.name}/registration.yaml") enabled;

    })
  ];
}
