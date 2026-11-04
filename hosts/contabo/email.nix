# Experimental Matrix <-> IMAP/SMTP bridge (Matrimail).
# The service is opt-in; see email-bridge/README.md before enabling it.
{ config, lib, pkgs, ... }@args:
let
  cfg = config.contabo.emailBridge;
in
{
  options.contabo.emailBridge.enable = lib.mkEnableOption
    "experimental Matrimail bridge to existing email inboxes";
  options.contabo.emailBridge.package = lib.mkOption {
    type = lib.types.package;
    default = args.contaboMatrimail or (import ./email-bridge/package.nix {
      pkgs = import pkgs.path {
        system = pkgs.stdenv.hostPlatform.system;
        config.permittedInsecurePackages = [ "olm-3.2.16" ];
      };
    });
    description = "Pinned patched Matrimail package";
  };

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
          # If a reboot occurs after Synapse room deletion begins but before
          # native portal mappings are reset, do not restart the old bridge
          # and accidentally recreate/duplicate deleted conversation rooms.
          # The pre-start check uses privileged '+' because the private
          # administrator ledger is intentionally not readable by matrimail.
          ExecStartPre = "+${pkgs.writeShellScript "matrimail-clean-reset-guard" ''
            if [ -f /var/lib/contabo-admin/matrimail-owner-clean-reset.json ]; then
              ${pkgs.python3}/bin/python3 - <<'PY'
import json
from pathlib import Path
ledger=json.loads(Path('/var/lib/contabo-admin/matrimail-owner-clean-reset.json').read_text())
if ledger.get('phase') in ('deleting', 'native-reset'):
    raise SystemExit('Matrimail clean reset is incomplete; resume it before restarting bridge')
PY
            fi
          ''}";
          ExecStart = "${lib.getExe cfg.package} --config /var/lib/matrimail/config.yaml";
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
