{ pkgs, lib, ... }:
{
  home.packages = with pkgs; [ swaynotificationcenter libnotify ];

  xdg.configFile."swaync/style.css".source = ./style.css;
  xdg.configFile."swaync/config.json".source = ./config.json;

  # SwayNC is started once by Hyprland, so a Home Manager switch otherwise
  # leaves the already-running process on its old config/CSS. Reload it after
  # the new symlinks have been written.
  home.activation.reloadSwaync =
    lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      if ${pkgs.procps}/bin/pgrep -x swaync >/dev/null 2>&1; then
        ${pkgs.swaynotificationcenter}/bin/swaync-client --reload-config || true
        ${pkgs.swaynotificationcenter}/bin/swaync-client --reload-css || true
      fi
    '';
}
