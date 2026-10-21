# Matrix Synapse and Cinny on the existing Contabo host.
# The Matrix server_name is permanent; do not change it after initialization.
{ config, pkgs, ... }:
{
  services.postgresql.ensureUsers = [
    { name = "matrix-synapse"; }
  ];

  # Synapse requires a UTF-8 PostgreSQL database using the C locale.
  # Create it once without touching Nextcloud's existing databases.
  systemd.services.matrix-synapse-database = {
    description = "Ensure the Matrix Synapse PostgreSQL database exists";
    requires = [ "postgresql.service" ];
    after = [ "postgresql.service" ];
    before = [ "matrix-synapse.service" ];
    requiredBy = [ "matrix-synapse.service" ];
    path = [
      config.services.postgresql.package
      pkgs.coreutils
      pkgs.gnugrep
    ];
    serviceConfig = {
      Type = "oneshot";
      User = "postgres";
      Group = "postgres";
      RemainAfterExit = true;
    };
    script = ''
      set -eu
      if ! psql -d postgres -Atqc "SELECT 1 FROM pg_database WHERE datname = 'matrix-synapse'" | grep -qx 1; then
        createdb -O matrix-synapse -T template0 -E UTF8 --lc-collate=C --lc-ctype=C matrix-synapse
      fi
    '';
  };

  services.matrix-synapse = {
    enable = true;

    settings = {
      server_name = "iniyanjoseph.com";
      public_baseurl = "https://matrix.iniyanjoseph.com/";
      enable_registration = false;
      report_stats = false;
      url_preview_enabled = false;
      max_upload_size = "50M";
      database.name = "psycopg2";
      database.args = {
        database = "matrix-synapse";
        user = "matrix-synapse";
        # No password: PostgreSQL peer authentication over localhost socket.
      };
      listeners = [
        {
          port = 8008;
          bind_addresses = [ "127.0.0.1" ];
          type = "http";
          tls = false;
          x_forwarded = true;
          resources = [
            { names = [ "client" ]; compress = true; }
            { names = [ "federation" ]; compress = false; }
          ];
        }
      ];
    };

    # Kept out of the public Nix store and Git; systemd copies the secret into
    # a private credentials directory for Synapse at service startup.
    extraConfigFiles = [
      "/run/credentials/matrix-synapse.service/registration.yaml"
    ];
  };

  systemd.services.matrix-synapse.serviceConfig.LoadCredential = [
    "registration.yaml:/var/lib/secrets/matrix-registration.yaml"
  ];

  services.nginx = {
    recommendedProxySettings = true;
    virtualHosts = {
      "matrix.iniyanjoseph.com" = {
        enableACME = true;
        forceSSL = true;
        locations = {
          "/_matrix" = {
            proxyPass = "http://127.0.0.1:8008";
            extraConfig = ''
              client_max_body_size 50M;
              proxy_http_version 1.1;
            '';
          };
          "/_synapse/client" = {
            proxyPass = "http://127.0.0.1:8008";
            extraConfig = ''
              client_max_body_size 50M;
              proxy_http_version 1.1;
            '';
          };
          "/" = { extraConfig = "return 404;"; };
        };
      };

      "chat.iniyanjoseph.com" = {
        enableACME = true;
        forceSSL = true;
        root = pkgs.cinny.override {
          conf = {
            defaultHomeserver = 0;
            homeserverList = [ "matrix.iniyanjoseph.com" ];
            allowCustomHomeservers = true;
            featuredCommunities = {
              openAsDefault = false;
              spaces = [ ];
              rooms = [ ];
              servers = [ ];
            };
          };
        };
        # Cinny uses client-side routes (e.g. /room/...). Serve its
        # entrypoint rather than returning a filesystem 404 on refresh.
        locations."/".tryFiles = "$uri $uri/ /index.html";
      };
    };
  };

  # Nextcloud already opens 80/443; never expose Synapse's port 8008 directly.
}
