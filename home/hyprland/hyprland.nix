{ inputs, pkgs, ... }:
{
  home.packages = with pkgs; [
    swww
    grim
    grimblast
    wl-clip-persist
    # cliphist
    glib
    direnv
    wayland
  ];
  wayland.windowManager.hyprland = {
    enable = true;

    xwayland = {
      enable = true;
    };
  };

  services.cliphist.enable = true;
}
