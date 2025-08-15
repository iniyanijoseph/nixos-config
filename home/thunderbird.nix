{pkgs, ...}:
{
  home.packages=with pkgs; [legcord];
  programs.thunderbird = {
    enable = true;
    profiles.wug.isDefault = true;
  };
}
