{ inputs, pkgs, ... }:
{
  home.packages = with pkgs; [
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
  services.hyprpaper = {
    enable = true;
    settings = {
      preload=["/home/wug/Pictures/wallpaper.jpg" "/home/wug/Pictures/Camera/ValerieChristmas.jpg" ];
      # wallpaper=[", /home/wug/Pictures/wallpaper.jpg"];
      wallpaper=[", /home/wug/Pictures/Camera/ValerieChristmas.jpg"];
    };
  };
}
