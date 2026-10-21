{ pkgs, ... }:
{
  # Baseline mirrored from the working Nextcloud setup.
  # BEFORE switching to this flake on Contabo, replace this file with the
  # CURRENT /etc/nixos/nextcloud.nix from the VPS if it has newer changes.
  services.nextcloud = {
    enable = true;
    package = pkgs.nextcloud33;
    hostName = "cloud.iniyanjoseph.com";
    https = true;
    database.createLocally = true;
    configureRedis = true;
    maxUploadSize = "4G";

    config = {
      dbtype = "pgsql";
      adminuser = "wug";
      # Must already exist on the VPS; do not commit its contents.
      adminpassFile = "/var/lib/secrets/nextcloud-admin";
    };

    settings = {
      default_phone_region = "US";
      maintenance_window_start = 1;
      log_type = "systemd";

      # Nextcloud Memories: absolute Nix store paths for EXIF and video tools.
      "memories.exiftool" = "${pkgs.exiftool}/bin/exiftool";
      "memories.exiftool_no_local" = true;
      "memories.vod.ffmpeg" = "${pkgs.ffmpeg-headless}/bin/ffmpeg";
      "memories.vod.ffprobe" = "${pkgs.ffmpeg-headless}/bin/ffprobe";
      preview_ffmpeg_path = "${pkgs.ffmpeg-headless}/bin/ffmpeg";
    };
  };

  # Let Memories' scheduled indexing find Perl.
  systemd.services.nextcloud-cron.path = [ pkgs.perl ];

  services.nginx.virtualHosts."cloud.iniyanjoseph.com" = {
    forceSSL = true;
    enableACME = true;
  };

  security.acme = {
    acceptTerms = true;
    defaults.email = "contact@iniyanjoseph.com";
  };

  networking.firewall.allowedTCPPorts = [ 80 443 ];
}
