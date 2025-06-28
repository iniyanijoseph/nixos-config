{pkgs, ...}:
{
  home.packages=with pkgs; [webcord-vencord];
  programs.thunderbird = {
    enable = true;
    profiles.wug.isDefault = true;
  };
}
