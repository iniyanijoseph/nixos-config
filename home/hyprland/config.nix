{ config, lib, pkgs, ... }:
{
  # Hyprland 0.56's native Lua configuration. Home Manager creates the small
  # ~/.config/hypr/hyprland.lua entry point and loads this module from it.
  wayland.windowManager.hyprland.extraLuaFiles."desktop" = {
    content = ./config.lua;
    autoLoad = true;
  };

  # nwg-displays 0.4.3 writes Lua alongside its legacy .conf output. Preserve
  # an existing monitor/workspace layout on the first switch if those Lua
  # files have not been generated yet; subsequent changes come directly from
  # nwg-displays' monitors.lua and workspaces.lua.
  home.activation.migrateHyprlandDisplayFiles =
    lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      ${pkgs.python3}/bin/python ${./migrate-displays.py} \
        "${config.xdg.configHome}/hypr"
    '';
}
