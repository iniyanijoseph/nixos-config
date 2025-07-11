{pkgs, ...}:
{
  home.packages=with pkgs; [dorion];
  programs.thunderbird = {
    enable = true;
    profiles.wug.isDefault = true;
  };
}
