{ inputs, pkgs, ... }:
{
  home.packages = with pkgs; [
    grim
    grimblast
    wl-clip-persist
    glib
    wayland
    hyprpicker
    hyprpaper
    swaybg
  ];
  wayland.windowManager.hyprland = {
    enable = true;

    xwayland.enable = true;

    # Hyprland 0.56's native configuration API. Home Manager generates the
    # hyprland.lua entry point and loads the declarative modules from it.
    configType = "lua";
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
