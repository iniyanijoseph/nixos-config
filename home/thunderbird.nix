{pkgs, ...}:
{
  home.packages=with pkgs; [zoom-us slack discord whatsapp-electron];
  programs.thunderbird = {
    enable = true;
    profiles.wug.isDefault = true;
  };
}
