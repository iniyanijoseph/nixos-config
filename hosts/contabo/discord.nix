# Personal Discord account bridge. The bridge uses the legacy mautrix-discord
# configuration layout and fetches history into newly created Matrix rooms.
{ ... }:
{
  services.mautrix-discord = {
    enable = true;
    registerToSynapse = true;
    settings = {
      homeserver = {
        domain = "iniyanjoseph.com";
        address = "http://127.0.0.1:8008";
      };
      appservice = {
        address = "http://127.0.0.1:29334";
        hostname = "127.0.0.1";
        port = 29334;
        database = {
          type = "sqlite3";
          uri = "file:/var/lib/mautrix-discord/mautrix-discord.db?_txlock=immediate";
          max_open_conns = 20;
          max_idle_conns = 2;
        };
      };
      bridge = {
        permissions = {
          "*" = "block";
          "@me:iniyanjoseph.com" = "admin";
        };
        # Stage initial DM portal creation to avoid simultaneous huge backfills.
        startup_private_channel_create_limit = 5;
        sync_direct_chat_list = true;
        # Bound each initial fetch batch; massive parallel history requests
        # previously triggered Discord rate limiting and HTML error responses.
        # This does NOT automatically replay incomplete earlier backfills.
        backfill.forward_limits = {
          initial = {
            dm = 500;
            channel = 200;
            thread = 200;
          };
          missed = {
            dm = -1;
            channel = -1;
            thread = -1;
          };
          max_guild_members = -1;
        };
        encryption = {
          allow = true;
          default = true;
          require = true;
        };
        provisioning.shared_secret = "disable";
      };
    };
  };

  # mautrix-discord 0.7.6 is still linked against deprecated libolm.
  # Narrowly allow only this pinned insecure package while the bridge
  # migrates; do not enable NIXPKGS_ALLOW_INSECURE globally.
  nixpkgs.config.permittedInsecurePackages = [ "olm-3.2.16" ];
}
