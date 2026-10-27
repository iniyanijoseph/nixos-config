# Declarative Nextcloud Calendar, Contacts, and Tasks.
#
# Staged and disabled until the currently installed app list and the appstore
# state are audited. Existing Memories is installed statefully in store-apps:
# don't replace/update it while metadata correctness is unresolved.
{ config, lib, ... }:
let
  cfg = config.contabo.googleSuite;
  apps = config.services.nextcloud.package.packages.apps;
in {
  options.contabo.googleSuite.enable = lib.mkEnableOption
    "declarative Nextcloud Calendar, Contacts, and Tasks";

  config = lib.mkIf cfg.enable {
    # Package versions follow the pinned Nextcloud major version; no unstable
    # web download, unpinned app package or secret embedded in the Nix store.
    services.nextcloud.extraApps = {
      inherit (apps) calendar contacts tasks;
    };
    services.nextcloud.extraAppsEnable = true;

    # Memories is already installed in /var/lib/nextcloud/store-apps.
    # Keep that stateful app available while transitioning other apps.
    services.nextcloud.appstoreEnable = true;
  };
}
