{ pkgs, ... }:
{
  # Small subset of desktop conveniences; deliberately no GUI/TeX toolchain.
  programs.fish.enable = true;
  environment.systemPackages = with pkgs; [
    helix git gh curl wget htop btop ripgrep fd jq
  ];
  environment.shellAliases = {
    nixedit = "sudoedit /etc/nixos/hosts/contabo/configuration.nix";
    nixup = "sudo nixos-rebuild switch --flake /etc/nixos/hosts/contabo#contabo";
  };
  environment.variables.EDITOR = "hx";
}
