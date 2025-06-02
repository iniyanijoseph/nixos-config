{ pkgs, inputs, ... }:
{
  home.packages = [ pkgs.superfile ];

  xdg.configFile."superfile/config.toml".source = ./config.toml;
  xdg.configFile."superfile/theme/gruvbox-dark-hard.toml".source = ./gruvbox-dark-hard.toml;
}
