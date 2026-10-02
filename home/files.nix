{ pkgs, ... }:
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

  # Graphical fallback for portal requests. Nemo is still the normal file
  # manager; Zenity supplies the GTK file-selection dialog because Nemo itself
  # cannot return a selected path to the XDG FileChooser portal.
  gtkFilechooserFallback = pkgs.writeShellApplication {
    name = "gtk-portal-filechooser";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.zenity
    ];
    text = ''
      set -eu

      multiple="$1"
      directory="$2"
      save="$3"
      path="$4"
      out="$5"

      if [[ -z "$path" ]]; then
        path="$HOME/"
      fi

      if [[ "$directory" == "1" ]]; then
        if selection="$(zenity --file-selection --directory --title="Select folder" --filename="$path")"; then
          printf '%s\\n' "$selection" > "$out"
        else
          : > "$out"
        fi
      elif [[ "$save" == "1" ]]; then
        if selection="$(zenity --file-selection --save --confirm-overwrite --title="Save file" --filename="$path")"; then
          printf '%s\\n' "$selection" > "$out"
        else
          : > "$out"
        fi
      elif [[ "$multiple" == "1" ]]; then
        if selection="$(zenity --file-selection --multiple --separator="\n" --title="Select files" --filename="$path")"; then
          printf '%s\\n' "$selection" > "$out"
        else
          : > "$out"
        fi
      else
        if selection="$(zenity --file-selection --title="Select file" --filename="$path")"; then
          printf '%s\\n' "$selection" > "$out"
        else
          : > "$out"
        fi
      fi
    '';
  };

  # Keep the portal wrapper self-contained in the Nix store. The upstream
  # yazi-wrapper.sh relies on TERMCMD and the portal service's PATH, which is
  # easy to lose across systemd/DBus activation and can make Firefox's Upload
  # button appear to do nothing.
  termfilechooserWrapper = pkgs.writeShellApplication {
    name = "yazi-portal-filechooser";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.kitty
      pkgs.yazi
    ];
    text = ''
      set -eu

      multiple="$1"
      directory="$2"
      save="$3"
      path="$4"
      out="$5"

      if [[ -z "$path" ]]; then
        path="$HOME"
      fi

      cwd_out="$out.cwd"

      if [[ "$save" == "1" ]]; then
        set -- --chooser-file="$out" "$path"
      elif [[ "$directory" == "1" ]]; then
        set -- --chooser-file="$out" --cwd-file="$cwd_out" "$path"
      else
        set -- --chooser-file="$out" "$path"
      fi

      if kitty --class termfilechooser --title "File chooser" yazi "$@"; then
        if [[ "$directory" == "1" ]]; then
          if [[ ! -s "$out" && -s "$cwd_out" ]]; then
            cat "$cwd_out" > "$out"
          fi
          rm -f "$cwd_out"
        fi
      else
        rm -f "$cwd_out"
        ${gtkFilechooserFallback}/bin/gtk-portal-filechooser "$multiple" "$directory" "$save" "$path" "$out"
      fi
    '';
  };
in
{
  programs.yazi = {
    enable = true;
    enableFishIntegration = true;
    # Pin to current behavior explicitly (silences the 26.05 default-change
    # warning; also matches the existing fish/functions/yy.fish on disk).
    shellWrapperName = "yy";
    extraPackages = with pkgs; [
      less
      trash-cli
    ];
    keymap = {
      mgr.prepend_keymap = [
        {
          on = "<C-n>";
          run = "shell --block -- ${pkgs.kitty}/bin/kitten dnd --exit-on=drag-finish,esc-key %s";
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
          desc = "Enter directory (Helix right)";
        }
        {
          on = "l";
          run = "leave";
          desc = "Leave directory (Helix left)";
        }
      ];
    };
  };

  # Prefer Yazi for portal-aware Open/Save dialogs; fall back to a GTK
  # chooser if Kitty/Yazi errors. Keep Nemo as the normal graphical file manager.
  xdg.configFile."xdg-desktop-portal-termfilechooser/config".text = ''
    [filechooser]
    cmd=${termfilechooserWrapper}/bin/yazi-portal-filechooser
    default_dir=$HOME
    create_help_file=0
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
