{ inputs, pkgs, ... }:
{
  programs.firefox.enable = true;
  home.packages = with pkgs; [openconnect brave];
}
