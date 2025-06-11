{ inputs, pkgs, ... }:
{
  home.packages = with pkgs; [
    swww
    grim
    grimblast
    wl-clip-persist
    glib
    direnv
  ];
  wayland.windowManager.hyprland = {
    enable = true;

    xwayland = {
      enable = true;
    };
  };

  services.cliphist.enable = true;
}
