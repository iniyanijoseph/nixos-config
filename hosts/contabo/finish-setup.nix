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
    after = [
      "network-online.target"
      "matrix-synapse.service"
      "nginx.service"
      "mautrix-whatsapp.service"
      "postgresql.service"
      "nextcloud-setup.service"
    ];
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
      # A system switch re-starts active targets. A oneshot start job would
      # remain pending until this worker exits, making the switch wait for
      # the same worker that is waiting for it. Mark startup complete at exec.
      Type = "exec";
      ExecStart = "${state}/runner/bin/contabo-finish-setup";
      UMask = "0077";
      TimeoutStartSec = "infinity";
      StandardOutput = "append:${state}/run.log";
      StandardError = "append:${state}/run.log";
    };
  };

  # Photo remediation is gated by a verified, read-only email-room audit.
  # A periodic one-shot retry avoids re-running the entire commissioning
  # launcher merely because an IMAP history import is still in progress.
  # Both paths acquire the same worker.lock and share the pinned runner.
  systemd.services.contabo-post-mail = {
    description = "Continue backed-up photo remediation after Matrimail reconciliation";
    wants = [ "network-online.target" ];
    after = [ "network-online.target" "matrix-synapse.service" "matrimail.service" "nextcloud-setup.service" ];
    unitConfig = {
      ConditionHost = "contabo";
      ConditionPathExists = [
        "${state}/resume-on-boot"
        "${state}/runner/bin/contabo-finish-setup"
        "!${state}/photo-after-email-complete"
      ];
    };
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${state}/runner/bin/contabo-finish-setup --after-email";
      UMask = "0077";
      TimeoutStartSec = "infinity";
      StandardOutput = "append:${state}/run.log";
      StandardError = "append:${state}/run.log";
      # Missing email history/temporary IMAP failure is a deferred retry,
      # not an assertion that photo work was completed.
      SuccessExitStatus = [ 2 ];
    };
  };

  systemd.timers.contabo-post-mail = {
    description = "Retry email-first photo commissioning without touching Discord import";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "30min";
      OnUnitInactiveSec = "2h";
      RandomizedDelaySec = "5min";
      Persistent = false;
      Unit = "contabo-post-mail.service";
    };
  };

}
