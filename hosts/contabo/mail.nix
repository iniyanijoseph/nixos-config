# Stalwart Mail Server 0.15.5 (pinned by hosts/contabo/flake.nix).
#
# Opt-in. DO NOT enable until prerequisites in mail-server/README.md are met.
# The new Stalwart 0.16 JSON-based documentation DOES NOT describe this
# version's TOML configuration; keep the 0.15 package and NixOS module paired.
{ config, lib, ... }:
let
  cfg = config.contabo.mail;
  host = "mail.iniyanjoseph.com";
  certDir = "/var/lib/acme/${host}";
in
{
  options.contabo.mail.enable = lib.mkEnableOption
    "private Stalwart IMAP/SMTP mailbox on Contabo";

  config = lib.mkIf cfg.enable {
    services.stalwart = {
      enable = true;
      stateVersion = "26.05";
      dataDir = "/var/lib/stalwart";
      openFirewall = false; # Expose only the explicitly listed mail ports.

      settings = {
        server = {
          hostname = host;
          listener = {
            smtp = { protocol = "smtp"; bind = [ "[::]:25" ]; };
            submission = { protocol = "smtp"; bind = [ "[::]:587" ]; };
            submissions = {
              protocol = "smtp";
              bind = [ "[::]:465" ];
              tls.implicit = true;
            };
            imaps = {
              protocol = "imap";
              bind = [ "[::]:993" ];
              tls.implicit = true;
            };
            # Management/JMAP HTTP only via existing Nginx, never public 8081.
            web = {
              protocol = "http";
              bind = [ "127.0.0.1:8081" ];
            };
          };
        };

        # Certificate supplied by NixOS ACME/Nginx; no key material in Git.
        certificate.default = {
          cert = "%{file:${certDir}/fullchain.pem}%";
          private-key = "%{file:${certDir}/key.pem}%";
          default = true;
        };
        # Recovery administrator only. Replace with a scoped normal admin,
        # then decide whether to remove this fallback login.
        authentication.fallback-admin = {
          user = "admin";
          secret = "%{file:/run/credentials/stalwart.service/admin-password}%";
        };
        # Ensure local file macros and server configuration remain local.
        config."local-keys" = [
          "store.*"
          "directory.*"
          "tracer.*"
          "!server.blocked-ip.*"
          "!server.allowed-ip.*"
          "server.*"
          "authentication.fallback-admin.*"
          "cluster.*"
          "config.local-keys.*"
          "storage.data"
          "storage.blob"
          "storage.lookup"
          "storage.fts"
          "storage.directory"
          "certificate.*"
          "http.use-x-forwarded"
        ];
        http.use-x-forwarded = true;
      };

      # This secret MUST be created locally before enabling the module.
      credentials.admin-password = "/var/lib/secrets/stalwart-admin-password";
    };

    # Nginx already owns HTTP 80/HTTPS 443 for Nextcloud and Synapse.
    # The mail admin/JMAP endpoint is proxied; IMAP/SMTP go to Stalwart.
    services.nginx.virtualHosts.${host} = {
      enableACME = true;
      forceSSL = true;
      locations."/" = {
        proxyPass = "http://127.0.0.1:8081";
        extraConfig = ''
          proxy_http_version 1.1;
          client_max_body_size 50m;
        '';
      };
    };
    # Allow the unprivileged Stalwart process to read the renewal-managed key.
    security.acme.certs.${host}.group = "stalwart";

    networking.firewall.allowedTCPPorts = [ 25 465 587 993 ];

    # The ACME cert is already obtained by the nginx host. On renewal, reload
    # the mail service so Stalwart re-reads the certificate files.
    security.acme.certs.${host}.postRun = "systemctl try-restart stalwart.service";
    systemd.services.stalwart.after = [ "acme-${host}.service" ];
  };
}
