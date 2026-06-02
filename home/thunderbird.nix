{pkgs, ...}:
{
  home.packages=with pkgs; [zoom-us slack];
  programs.thunderbird = {
    enable = true;
    profiles.wug.isDefault = true;
  };
}
