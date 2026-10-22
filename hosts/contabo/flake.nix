{
  description = "Contabo NixOS VPS (separate stable flake in the desktop config repo)";

  # Intentionally separate from the desktop's nixos-unstable lock file.
  # Copy the working /etc/nixos/flake.lock here on first migration.
  inputs = {
    # Emergency PHP fixes for CVE-2026-109618 / CVE-2026-109619.
    # NixOS 26.05 backport merge commit (PHP 8.4.27).
    # Return to the nixos-26.05 channel only after verifying that the
    # channel contains this security patch.
    nixpkgs.url = "github:NixOS/nixpkgs/8c259fc0dd1f3ccc1aaf4f9156ab16b7328b5a4f";
    disko.url = "github:nix-community/disko";
    disko.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { nixpkgs, disko, ... }:
    let
      system = "x86_64-linux";
      emailPkgs = import nixpkgs {
        inherit system;
        # Matrimail currently requires deprecated libolm for Matrix E2EE.
        # Keep this exception limited to the opt-in development shell.
        config.permittedInsecurePackages = [ "olm-3.2.16" ];
      };
    in {
    devShells.x86_64-linux.email-bridge = emailPkgs.mkShell {
      packages = [
        emailPkgs.go
        emailPkgs.git
        emailPkgs.pkg-config
        emailPkgs.olm
        emailPkgs.gcc
      ];
    };

    nixosConfigurations.contabo = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        disko.nixosModules.disko
        ./configuration.nix
      ];
    };
  };
}
