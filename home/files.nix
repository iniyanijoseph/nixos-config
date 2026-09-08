{ lib, pkgs, ... }:
let
  trashEmptyAll = pkgs.writeShellApplication {
    name = "trash-empty-all";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.trash-cli
    ];
    text = ''
      item_count="$(trash-list | wc -l)"
      if [[ "$item_count" -eq 0 ]]; then
        echo "Trash is already empty."
        read -r -p "Press Enter to return to Yazi..."
        exit 0
      fi

      read -r -p "Permanently delete all $item_count trash entries? Type EMPTY to confirm: " confirmation
      if [[ "$confirmation" == "EMPTY" ]]; then
        trash-empty
        echo "Trash emptied."
      else
        echo "Cancelled; no trash was removed."
      fi
      read -r -p "Press Enter to return to Yazi..."
    '';
  };

  trashEmptyByAge = pkgs.writeShellApplication {
    name = "trash-empty-by-age";
    runtimeInputs = [ pkgs.trash-cli ];
    text = ''
      read -r -p "Permanently delete trash older than how many days? " days

      case "$days" in
        ""|*[!0-9]*)
          echo "Please enter a non-negative whole number."
          read -r -p "Press Enter to return to Yazi..."
          exit 1
          ;;
      esac

      read -r -p "Permanently delete trash older than $days days? Type EMPTY to confirm: " confirmation
      if [[ "$confirmation" == "EMPTY" ]]; then
        trash-empty "$days"
        echo "Old trash emptied."
      else
        echo "Cancelled; no trash was removed."
      fi
      read -r -p "Press Enter to return to Yazi..."
    '';
  };

  termfilechooserWrapper =
    "${pkgs.xdg-desktop-portal-termfilechooser}/share/xdg-desktop-portal-termfilechooser/yazi-wrapper.sh";
  termfilechooserPath = lib.makeBinPath [
    pkgs.coreutils
    pkgs.gnused
    pkgs.less
    pkgs.trash-cli
    pkgs.yazi
  ];
in
{
  programs.yazi = {
    enable = true;
    enableFishIntegration = true;
    # Pin to current behavior explicitly (silences the 26.05 default-change
    # warning; also matches the existing fish/functions/yy.fish on disk).
    shellWrapperName = "yy";
    extraPackages = with pkgs; [
      dragon-drop
      less
      trash-cli
    ];
    keymap = {
      mgr.prepend_keymap = [
        {
          on = "<C-n>";
          run = "shell -- ${pkgs.dragon-drop}/bin/dragon-drop -x -i -T -a %s";
          desc = "Drag selected files";
        }
        {
          on = "?";
          run = "help";
          desc = "Show shortcuts";
        }
        {
          on = [ "R" "l" ];
          run = "shell 'trash-list | less' --block";
          desc = "List trash";
        }
        {
          on = [ "R" "r" ];
          run = "shell 'trash-restore' --block";
          desc = "Restore from trash";
        }
        {
          on = [ "R" "e" ];
          run = "shell '${trashEmptyAll}/bin/trash-empty-all' --block";
          desc = "Empty all trash";
        }
        {
          on = [ "R" "d" ];
          run = "shell '${trashEmptyByAge}/bin/trash-empty-by-age' --block";
          desc = "Empty trash older than N days";
        }
      ];
      mgr.append_keymap = [
        {
          on = "h";
          run = "enter";
        }
        {
          on = "l";
          run = "leave";
        }
      ];
    };
  };

  # Use Yazi for portal-aware Open/Save dialogs while keeping Nemo installed
  # for tasks that benefit from a graphical file manager.
  xdg.configFile."xdg-desktop-portal-termfilechooser/config".text = ''
    [filechooser]
    cmd=${termfilechooserWrapper}
    default_dir=$HOME
    env=TERMCMD='${pkgs.kitty}/bin/kitty --class termfilechooser --title "File chooser"'
    env=PATH=${termfilechooserPath}:/run/current-system/sw/bin:/etc/profiles/per-user/wug/bin
    open_mode=suggested
    save_mode=last
  '';

  home.packages = with pkgs; [
    nemo
    rclone
  ];

  dconf.settings = {
    "org/nemo/preferences" = {
      always-use-browser = true;
      # click-double-parent-folder = true;
      close-device-view-on-device-eject = true;
      date-font-choice = "auto-mono";
      date-format = "iso";
      last-server-connect-method = 3;
      quick-renames-with-pause-in-between = true;
      show-edit-icon-toolbar = false;
      show-full-path-titles = false;
      show-hidden-files = true;
      show-home-icon-toolbar = true;
      show-new-folder-icon-toolbar = true;
      show-open-in-terminal-toolbar = false;
      show-search-icon-toolbar = false;
      show-show-thumbnails-toolbar = false;
      thumbnail-limit = 10485760;
    };
    "org/nemo/preferences/menu-config" = {
      background-menu-open-as-root = false;
      selection-menu-open-as-root = false;
      selection-menu-open-in-terminal = false;
      selection-menu-scripts = false;
    };
    "org/nemo/search" = {
      search-reverse-sort = false;
      search-sort-column = "name";
    };
    "org/nemo/window-state" = {
      maximized = true;
      network-expanded = true;
      side-pane-view = "places";
      sidebar-bookmark-breakpoint = 2;
      sidebar-width = 220;
      start-with-sidebar = true;
    };
  };
}
