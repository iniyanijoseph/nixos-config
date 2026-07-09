{ pkgs, ... }:

{
  home.packages = with pkgs; [
    geary
    gcr
  ];

  services.gnome-keyring.enable = true;

  # Ensure the freedesktop secret service can find the user display/session env.
  xdg.portal.enable = true;
}
