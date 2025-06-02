{config, pkgs, ...}:
{
  home.username = "wug";
  home.homeDirectory = "/home/wug";
  home.stateVersion = "25.05";

  programs.home-manager.enable = true;
}
