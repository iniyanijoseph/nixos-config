{ inputs, pkgs, ... }:
{
  programs.firefox.enable = true;
  programs.floorp.enable = true;
  home.packages = with pkgs; [luakit];
}
