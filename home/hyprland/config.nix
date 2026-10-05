{ config, lib, pkgs, ... }:
{
  # Hyprland 0.56's native Lua configuration. Home Manager creates the small
  # ~/.config/hypr/hyprland.lua entry point and loads these modules from it.
  wayland.windowManager.hyprland.extraLuaFiles."desktop" = {
    content = ./config.lua;
    autoLoad = true;
  };

  wayland.windowManager.hyprland.extraLuaFiles."startup-routing" = {
    content = ./startup-routing.lua;
    autoLoad = true;
  };

  # Load after the main desktop module so these bindings replace the older,
  # invalid SwayOSD brightness commands from config.lua.
  wayland.windowManager.hyprland.extraLuaFiles."zz-brightness" = {
    content = ./brightness.lua;
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

  # Home Manager updates the Lua config on disk, but the running compositor
  # otherwise keeps the old rules until it is explicitly reloaded. Find the
  # active Hyprland instance from its runtime socket and reload it after each
  # activation so window/workspace changes take effect immediately.
  home.activation.reloadHyprland =
    lib.hm.dag.entryAfter [ "migrateHyprlandDisplayFiles" ] ''
      runtime="''${XDG_RUNTIME_DIR:-/run/user/$(${pkgs.coreutils}/bin/id -u)}"
      if [ -d "$runtime/hypr" ]; then
        for instance_dir in "$runtime"/hypr/*; do
          if [ -S "$instance_dir/.socket.sock" ]; then
            signature="$(${pkgs.coreutils}/bin/basename "$instance_dir")"
            XDG_RUNTIME_DIR="$runtime" \
            HYPRLAND_INSTANCE_SIGNATURE="$signature" \
              ${pkgs.hyprland}/bin/hyprctl reload >/dev/null 2>&1 || true
            break
          fi
        done
      fi
    '';

}
