{pkgs, ...}:
{
  home.packages=with pkgs; [];
  programs.thunderbird = {
    enable = true;
    profiles.wug.isDefault = true;
  };
}
