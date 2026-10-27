# Boot resume for a previously started commissioning run. The launcher uses
# a runtime unit before this module has been deployed; no NixOS switch is
# needed merely to launch setup. Never write units to /etc imperatively.
{ ... }:
let
  state = "/var/lib/migration-queue/finish-setup";
in {
  systemd.services.contabo-finish-setup = {
    description = "Resume Contabo commissioning; see ${state}/summary.txt";
    wantedBy = [ "multi-user.target" ];
    wants = [ "network-online.target" ];
    after = [ "network-online.target" ];
    unitConfig = {
      ConditionHost = "contabo";
      ConditionPathExists = [
        "${state}/resume-on-boot"
        "${state}/runner/bin/contabo-finish-setup"
      ];
    };
    # Deploying a newer system generation must not interrupt a photo repair.
    restartIfChanged = false;
    stopIfChanged = false;
    environment = {
      PYTHONDONTWRITEBYTECODE = "1";
      SYSTEMD_PAGER = "cat";
    };
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${state}/runner/bin/contabo-finish-setup";
      UMask = "0077";
      TimeoutStartSec = "infinity";
      StandardOutput = "append:${state}/run.log";
      StandardError = "append:${state}/run.log";
    };
  };
}
