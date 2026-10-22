#!/usr/bin/env bash
# Evaluate each *future* NixOS profile without building/switching/running it.
set -euo pipefail
cd /etc/nixos
for profile in mail matrimail sms slack all; do
  echo "=== NixOS future profile: $profile (evaluate ONLY) ==="
  BRIDGE_PROFILE="$profile" nix eval --impure --raw --expr '
    let
      f = builtins.getFlake (toString ./hosts/contabo);
      profile = builtins.getEnv "BRIDGE_PROFILE";
      system = f.inputs.nixpkgs.lib.nixosSystem {
        system = "x86_64-linux";
        modules = [
          f.inputs.disko.nixosModules.disko
          ./hosts/contabo/configuration.nix
          ({lib, ...}: {
            contabo.mail.enable = lib.mkForce (profile == "mail" || profile == "all");
            contabo.emailBridge.enable = lib.mkForce (profile == "matrimail" || profile == "all");
            contabo.messagingBridges.sms.enable = lib.mkForce (profile == "sms" || profile == "all");
            contabo.messagingBridges.slack.enable = lib.mkForce (profile == "slack" || profile == "all");
          })
        ];
      };
    in system.config.system.build.toplevel.drvPath
  '
  echo
done
echo "Finished evaluation. No service has been enabled or restarted."
