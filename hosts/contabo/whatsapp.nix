# WhatsApp linked-device bridge for the private Synapse homeserver.
# The NixOS module generates and registers the Matrix application service.
{ pkgs, ... }:
{
  services.mautrix-whatsapp = {
    enable = true;
    registerToSynapse = true;
    # Avoid deprecated/insecure libolm. This uses mautrix's experimental
    # pure-Go Olm implementation; verify encrypted chat behavior before reliance.
    package = pkgs.mautrix-whatsapp.override { withGoolm = true; };

    # Keep the encryption pickle key out of Git and the world-readable Nix store.
    environmentFile = "/var/lib/secrets/mautrix-whatsapp.env";

    settings = {
      homeserver = {
        domain = "iniyanjoseph.com";
        address = "http://127.0.0.1:8008";
      };
      appservice = {
        hostname = "127.0.0.1";
        port = 29318;
        address = "http://127.0.0.1:29318";
      };
      bridge = {
        permissions = {
          "*" = "block";
          "@me:iniyanjoseph.com" = "admin";
        };
      };
      # This key remains stable between service restarts.
      encryption = {
        allow = true;
        default = true;
        require = true;
        pickle_key = "$WHATSAPP_PICKLE_KEY";
      };
      provisioning.shared_secret = "disable";
      backfill = {
        enabled = true;
        max_initial_messages = 50;
      };
      network.history_sync = {
        max_initial_conversations = -1;
        request_full_sync = false;
      };
    };
  };
}
