{pkgs, ...}:
{
  home.packages = with pkgs; [ytmdesktop];
  programs.mpv.enable = true;
}
