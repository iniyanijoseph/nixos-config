{ config, lib, pkgs, ... }:
let
  cfg = config.contabo.discordNative;
  package = import ./package.nix { inherit pkgs; };
  name = "mautrix-discord-native";
  state = "/var/lib/${name}";
in {
  options.contabo.discordNative = {
    enable = lib.mkEnableOption "Discord archive pilot bridge";
    pilot = lib.mkOption { type = lib.types.bool; default = true; };
  };
  config = lib.mkMerge [
    {
      users.groups.${name} = {};
      users.users.${name} = { isSystemUser = true; group = name; home = state; };
      systemd.tmpfiles.rules = [ "d ${state} 0750 ${name} ${name} -" ];
    }
    (lib.mkIf cfg.enable {
      services.matrix-synapse.settings.app_service_config_files = [ "${state}/registration.yaml" ];
      systemd.services.matrix-synapse.serviceConfig.SupplementaryGroups = [ name ];
      systemd.services.${name} = {
        after = [ "matrix-synapse.service" "network-online.target" ];
        requires = [ "matrix-synapse.service" ];
        wants = [ "network-online.target" ];
        wantedBy = [ "multi-user.target" ];
        environment = { CONTABO_DISCORD_ARCHIVE = "${state}/archive.sqlite"; }
          // lib.optionalAttrs cfg.pilot { CONTABO_DISCORD_PILOT_FILE = "${state}/pilot-channel"; };
        serviceConfig = {
          User = name; Group = name; WorkingDirectory = state;
          ExecStart = "${lib.getExe package} -c ${state}/config.yaml";
          Restart = "on-failure"; RestartSec = "30s"; UMask = "0027";
          NoNewPrivileges = true; ProtectHome = true; ProtectSystem = "strict";
          PrivateTmp = true; ReadWritePaths = [ state ];
        };
      };
      services.restic.backups.contabo.paths = [ state ];
    })
  ];
}
