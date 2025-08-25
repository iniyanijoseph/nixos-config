{pkgs, ...}:
{
  home.packages=with pkgs; [discord];
  programs.thunderbird = {
    enable = true;
    profiles.wug.isDefault = true;
  };
}
