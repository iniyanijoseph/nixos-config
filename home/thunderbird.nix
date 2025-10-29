{pkgs, ...}:
{
  home.packages=with pkgs; [zoom-us];
  programs.thunderbird = {
    enable = true;
    profiles.wug.isDefault = true;
  };
}
