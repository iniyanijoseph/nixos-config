{pkgs, ...}:
{
  home.packages=with pkgs; [discordo goofcord];
  programs.thunderbird = {
    enable = true;
    profiles.wug.isDefault = true;
  };
}
