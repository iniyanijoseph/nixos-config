{ pkgs, ... }:
{
  home.packages = [ pkgs.wlr-which-key ];

  xdg.configFile."wlr-which-key/config.yaml".source = ./wlr-which-key-config.yaml;
}
