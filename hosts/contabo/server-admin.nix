{ config, lib, pkgs, ... }:
let
  admin = import ./server-admin-package.nix { inherit pkgs; };
  invitation = pkgs.runCommand "contabo-invitation-page" {} ''
    mkdir -p "$out/invite"
    cp ${./server-invite.html} "$out/invite/index.html"
  '';
in {
  environment.systemPackages = [ admin ];
  services.matrix-synapse.settings = {
    enable_registration = lib.mkForce true;
    registration_requires_token = true;
    enable_registration_without_verification = false;
    allow_guest_access = false;
    registrations_require_3pid = [];
    password_config.policy = { enabled = true; minimum_length = 12; };
  };
  services.nginx.virtualHosts."matrix.iniyanjoseph.com".locations."/invite/" = {
    root = invitation;
    extraConfig = ''
      add_header Cache-Control "no-store" always;
      add_header Referrer-Policy "no-referrer" always;
      add_header Content-Security-Policy "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'" always;
    '';
  };
  users.groups.contabo-stats = {};
  users.users.contabo-stats = { isSystemUser = true; group = "contabo-stats"; };
  systemd.tmpfiles.rules = [ "d /var/lib/contabo-admin 0750 root contabo-stats -" ];
  systemd.services.contabo-private-bridge-config = {
    description = "Apply pinned bridge settings while preserving private sessions";
    before = [ "matrix-synapse.service" "mautrix-gmessages.service" "mautrix-slack.service" "matrimail.service" "mautrix-discord-native.service" ];
    requiredBy = [ "matrix-synapse.service" ];
    after = [ "systemd-tmpfiles-setup.service" ];
    serviceConfig = {
      Type = "oneshot"; RemainAfterExit = true;
      ExecStart = "${admin}/bin/contabo-admin configure-bridges";
      UMask = "0077"; NoNewPrivileges = true; ProtectHome = true;
      ProtectSystem = "strict";
      ReadWritePaths = [ "-/var/lib/mautrix-gmessages" "-/var/lib/mautrix-slack" "-/var/lib/matrimail" "-/var/lib/mautrix-discord-native" ];
    };
  };
  systemd.services.matrix-synapse.after = [ "contabo-private-bridge-config.service" ];
  systemd.services.contabo-bridge-checks = {
    description = "Read-only session and mapping checks for active messaging bridges";
    after = [ "matrix-synapse.service" "network-online.target" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${admin}/bin/contabo-admin bridges --core --record";
      UMask = "0077"; NoNewPrivileges = true; PrivateTmp = true;
      ProtectHome = true; ProtectSystem = "strict";
      ReadWritePaths = [ "/var/lib/contabo-admin" ];
    };
  };
  systemd.timers.contabo-bridge-checks = {
    wantedBy = [ "timers.target" ];
    timerConfig = { OnBootSec = "5min"; OnUnitActiveSec = "5min"; AccuracySec = "15s"; };
  };
  systemd.services.contabo-stats = {
    description = "Private loopback-only Matrix activity graph";
    unitConfig.ConditionPathExists = "/var/lib/contabo-admin/stats.html";
    serviceConfig = {
      User = "contabo-stats"; Group = "contabo-stats";
      ExecStart = "${admin}/bin/contabo-admin serve";
      Restart = "on-failure"; RestartSec = "5s";
      NoNewPrivileges = true; PrivateTmp = true; ProtectHome = true;
      ProtectSystem = "strict"; RestrictAddressFamilies = [ "AF_INET" ];
    };
  };
  systemd.services.contabo-whatsapp-secret = {
    description = "Preserve a private WhatsApp health-check API credential";
    before = [ "mautrix-whatsapp.service" ];
    requiredBy = [ "mautrix-whatsapp.service" ];
    unitConfig.ConditionPathExists = "/var/lib/secrets/mautrix-whatsapp.env";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${admin}/bin/contabo-admin whatsapp-secret";
      UMask = "0077"; NoNewPrivileges = true; ProtectHome = true;
      ProtectSystem = "strict"; ReadWritePaths = [ "/var/lib/secrets" ];
    };
  };
  systemd.services.mautrix-whatsapp.after = [ "contabo-whatsapp-secret.service" ];
  services.mautrix-whatsapp.settings.provisioning = {
    shared_secret = lib.mkForce "$WHATSAPP_PROVISIONING_SECRET";
    allow_matrix_auth = false;
    debug_endpoints = false;
  };
  services.journald.extraConfig = ''
    SystemMaxUse=300M
    RuntimeMaxUse=64M
    SystemMaxFileSize=32M
    MaxRetentionSec=14day
  '';
  nix.gc = { automatic = true; dates = "weekly"; options = "--delete-older-than 30d"; };
  nix.optimise = { automatic = true; dates = [ "weekly" ]; };
}
