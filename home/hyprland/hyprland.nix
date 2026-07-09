{ inputs, pkgs, ... }:
{
  home.packages = with pkgs; [
    grim
    grimblast
    wl-clip-persist
    glib
    direnv
    wayland
    hyprpicker
    hyprpaper
    swaybg
  ];
  wayland.windowManager.hyprland = {
    enable = true;

    xwayland.enable = true;

    # Pin to current behavior explicitly (silences the 26.05
    # default-change warning without changing anything).
    configType = "hyprlang";
  };

  services.cliphist.enable = true;
  # services.hyprpaper = {
  #   enable = true;
  #   settings = {
  #     ipc="on";
  #     preload=[ "/home/wug/Pictures/wallpaper.jpg" ];
  #     wallpaper=[
  #       ",/home/wug/Pictures/wallpaper.jpg"
  #     ];
  #   };
  # };
}
