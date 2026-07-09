{ pkgs, ... }:

{
  home.packages = with pkgs; [
    geary
    gcr
    gnome-control-center
  ];

  services.gnome-keyring.enable = true;

  xdg.portal.enable = true;
}
