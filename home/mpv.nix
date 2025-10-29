{pkgs, ...}:
{
  home.packages = with pkgs; [];
  programs.mpv.enable = true;
}
