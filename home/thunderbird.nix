{pkgs, ...}:
{
  home.packages=with pkgs; [dissent];
  programs.thunderbird = {
    enable = true;
    profiles.wug.isDefault = true;
  };
}
