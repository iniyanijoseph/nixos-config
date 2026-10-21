{
  description = "Contabo NixOS VPS (separate stable flake in the desktop config repo)";

  # Intentionally separate from the desktop's nixos-unstable lock file.
  # Copy the working /etc/nixos/flake.lock here on first migration.
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    disko.url = "github:nix-community/disko";
    disko.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { nixpkgs, disko, ... }: {
    nixosConfigurations.contabo = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        disko.nixosModules.disko
        ./configuration.nix
      ];
    };
  };
}
