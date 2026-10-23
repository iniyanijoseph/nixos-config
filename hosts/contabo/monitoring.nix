# Private Matrix migration status monitoring.
#
# Opt-in: package the existing stdlib-only scripts from the host's pinned
# flake and supervise them with durable systemd units. Do not enable alongside
# the existing transient jobs: two listeners would answer !status twice.
#
# Existing scripts need root-only secret/backup/checkpoint access. They run as
# root until status generation is split into a least-privilege read-only agent.
{ config, lib, pkgs, ... }:
let
  cfg = config.contabo.matrixMonitoring;

  reporter = pkgs.runCommand "contabo-matrix-status" {
    nativeBuildInputs = [ pkgs.makeWrapper ];
  } ''
    install -Dm0555 ${./matrix-alert.py} "$out/libexec/contabo/matrix-alert.py"
    install -Dm0555 ${./matrix-commands.py} "$out/libexec/contabo/matrix-commands.py"
    install -Dm0555 ${./matrix-periodic-status.py} "$out/libexec/contabo/matrix-periodic-status.py"
    install -Dm0555 ${./discord-archive/scope.py} "$out/libexec/contabo/discord-archive/scope.py"

    mkdir -p "$out/bin"
    makeWrapper ${pkgs.python3}/bin/python3 "$out/bin/matrix-command-listener" \
      --add-flags "$out/libexec/contabo/matrix-commands.py" \
      --prefix PATH : ${lib.makeBinPath [ pkgs.coreutils pkgs.systemd pkgs.restic pkgs.bash ]}
    makeWrapper ${pkgs.python3}/bin/python3 "$out/bin/matrix-periodic-status" \
      --add-flags "$out/libexec/contabo/matrix-periodic-status.py" \
      --prefix PATH : ${lib.makeBinPath [ pkgs.coreutils pkgs.systemd pkgs.restic pkgs.bash ]}
  '';

  restrictedService = {
    User = "root";
    Group = "root";
    UMask = "0077";
    NoNewPrivileges = true;
    PrivateTmp = true;
    ProtectHome = true;
    ProtectSystem = "strict";
    ProtectKernelTunables = true;
    ProtectKernelModules = true;
    ProtectControlGroups = true;
    ReadWritePaths = [ "/var/lib/migration-queue" ];
    Environment = "XDG_CACHE_HOME=/var/lib/migration-queue/.cache";
  };
in
{
  options.contabo.matrixMonitoring.enable = lib.mkEnableOption
    "declarative private Matrix command listener and 20-minute migration reports";

  config = lib.mkIf cfg.enable {
    systemd.services.matrix-command-listener = {
      description = "Private Contabo Matrix status command listener";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" "matrix-synapse.service" ];
      unitConfig.ConditionPathExists = "/var/lib/secrets/matrix-alerts.json";
      serviceConfig = restrictedService // {
        ExecStart = "${reporter}/bin/matrix-command-listener";
        Restart = "on-failure";
        RestartSec = "30s";
      };
    };

    systemd.services.matrix-periodic-status = {
      description = "Private Contabo migration progress report";
      wants = [ "network-online.target" ];
      after = [ "network-online.target" "matrix-synapse.service" ];
      unitConfig.ConditionPathExists = "/var/lib/secrets/matrix-alerts.json";
      serviceConfig = restrictedService // {
        Type = "oneshot";
        ExecStart = "${reporter}/bin/matrix-periodic-status";
      };
    };

    systemd.timers.matrix-periodic-status = {
      description = "Send a private Matrix progress report every 20 minutes";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "20min";
        OnUnitActiveSec = "20min";
        AccuracySec = "1min";
        Unit = "matrix-periodic-status.service";
      };
    };
  };
}
