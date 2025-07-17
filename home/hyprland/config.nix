{ ... }:
let
  browser = "firefox";
  terminal = "kitty";
in
{
  wayland.windowManager.hyprland = {
    settings = {

      exec-once = [
        "nm-applet &"
        "poweralertd &"
        "wl-clip-persist --clipboard both &"
        "wl-paste --watch cliphist store &"
        "swaync &"
        "hyprctl setcursor Bibata-Modern-Ice 24 &"
        "waybar"

        "[workspace 1 silent] ${browser}"
        "[workspace 9 silent] sleek-todo"
        "[workspace 10 silent] thunderbird & Dorion"
      ];

      input = {
        numlock_by_default = true;
        repeat_delay = 300;
        follow_mouse = 0;
        float_switch_override_focus = 0;
        mouse_refocus = 0;
        sensitivity = 0;
      };

      decoration = {
        rounding = 0;
        active_opacity = 1.0;
        inactive_opacity = 0.90;
        fullscreen_opacity = 1.0;

        blur = {
          enabled = true;
          size = 3;
          passes = 2;
          brightness = 1;
          contrast = 1.4;
          ignore_opacity = true;
          noise = 0;
          new_optimizations = true;
          xray = true;
        };

        shadow = {
          enabled = true;

          ignore_window = true;
          offset = "0 2";
          range = 20;
          render_power = 3;
          color = "rgba(00000055)";
        };
      };

      general = {
        "$mainMod" = "SUPER";
        gaps_in = 6;
        gaps_out = 12;
        border_size = 2;
        "col.active_border" = "rgb(98971A) rgb(CC241D) 45deg";
        "col.inactive_border" = "0x00000000";
        no_border_on_floating = false;
      };

      binds = {
        movefocus_cycles_fullscreen = true;
      };

      bind = [
        # show keybinds list
        "$mainMod, F1, exec, show-keybinds"

        # keybindings
        "$mainMod, Return, exec, ${terminal}"
        "$mainMod, B, exec, [workspace 1 silent] ${browser}"
        "$mainMod, Q, killactive,"
        "$mainMod, D, exec, rofi -show drun || pkill rofi"
        "$mainMod SHIFT, S, exec, grimblast --freeze copy area"
        "$mainMod, Escape, exec, swaylock"
        "$mainMod, N, exec, swaync-client -t -sw"

        # screenshot
        ",Print, exec, screenshot --copy"

        # switch focus
        # "$mainMod, left,  movefocus, l"
        # "$mainMod, right, movefocus, r"
        # "$mainMod, up,    movefocus, u"
        # "$mainMod, down,  movefocus, d"
        "$mainMod, l, movefocus, l"
        "$mainMod, j, movefocus, d"
        "$mainMod, k, movefocus, u"
        "$mainMod, h, movefocus, r"

        # "$mainMod, left,  alterzorder, top"
        # "$mainMod, right, alterzorder, top"
        # "$mainMod, up,    alterzorder, top"
        # "$mainMod, down,  alterzorder, top"
        "$mainMod, l, alterzorder, top"
        "$mainMod, j, alterzorder, top"
        "$mainMod, k, alterzorder, top"
        "$mainMod, h, alterzorder, top"

        # switch workspace
        "$mainMod, 1, workspace, 1"
        "$mainMod, 2, workspace, 2"
        "$mainMod, 3, workspace, 3"
        "$mainMod, 4, workspace, 4"
        "$mainMod, 5, workspace, 5"
        "$mainMod, 6, workspace, 6"
        "$mainMod, 7, workspace, 7"
        "$mainMod, 8, workspace, 8"
        "$mainMod, 9, workspace, 9"
        "$mainMod, 0, workspace, 10"

        # same as above, but switch to the workspace
        "$mainMod SHIFT, 1, movetoworkspacesilent, 1" # movetoworkspacesilent
        "$mainMod SHIFT, 2, movetoworkspacesilent, 2"
        "$mainMod SHIFT, 3, movetoworkspacesilent, 3"
        "$mainMod SHIFT, 4, movetoworkspacesilent, 4"
        "$mainMod SHIFT, 5, movetoworkspacesilent, 5"
        "$mainMod SHIFT, 6, movetoworkspacesilent, 6"
        "$mainMod SHIFT, 7, movetoworkspacesilent, 7"
        "$mainMod SHIFT, 8, movetoworkspacesilent, 8"
        "$mainMod SHIFT, 9, movetoworkspacesilent, 9"
        "$mainMod SHIFT, 0, movetoworkspacesilent, 10"
        "$mainMod CTRL, c, movetoworkspace, empty"

        # window control
        # "$mainMod SHIFT, left, movewindow, l"
        # "$mainMod SHIFT, right, movewindow, r"
        # "$mainMod SHIFT, up, movewindow, u"
        # "$mainMod SHIFT, down, movewindow, d"
        "$mainMod SHIFT, l, movewindow, l"
        "$mainMod SHIFT, j, movewindow, d"
        "$mainMod SHIFT, k, movewindow, u"
        "$mainMod SHIFT, h, movewindow, r"

        # "$mainMod CTRL, left, resizeactive, -80 0"
        # "$mainMod CTRL, right, resizeactive, 80 0"
        # "$mainMod CTRL, up, resizeactive, 0 -80"
        # "$mainMod CTRL, down, resizeactive, 0 80"
        "$mainMod CTRL, l, resizeactive, -80 0"
        "$mainMod CTRL, j, resizeactive, 0 80"
        "$mainMod CTRL, k, resizeactive, 0 -80"
        "$mainMod CTRL, h, resizeactive, 80 0"

        # "$mainMod ALT, left, moveactive,  -80 0"
        # "$mainMod ALT, right, moveactive, 80 0"
        # "$mainMod ALT, up, moveactive, 0 -80"
        # "$mainMod ALT, down, moveactive, 0 80"
        "$mainMod ALT, l, moveactive,  -80 0"
        "$mainMod ALT, j, moveactive, 0 80"
        "$mainMod ALT, k, moveactive, 0 -80"
        "$mainMod ALT, h, moveactive, 80 0"

        # media and volume controls
        # ",XF86AudioMute,exec, pamixer -t"
        ",XF86AudioPlay,exec, playerctl play-pause"
        ",XF86AudioNext,exec, playerctl next"
        ",XF86AudioPrev,exec, playerctl previous"
        ",XF86AudioStop,exec, playerctl stop"

        ",code:235,exec, nwg-displays"
        ",code:152,exec, nwg-displays"
        ",code:163,exec, thunderbird & Dorion"
        ",code:452,exec, thunderbird & Dorion"
        ",code:453,exec, blueman-manager"
        ",code:454,exec, ${browser}"
        ",code:256,exec, pavucontrol"
        ",code:179,exec, pavucontrol"
        ",code:164, exec, ${terminal} yazi"
        ",code:148, exec, ${terminal} yazi"
        ",code:180, exec, ${browser}"

        "$mainMod, mouse_down, workspace, e-1"
        "$mainMod, mouse_up, workspace, e+1"
        "$mainMod, T, exec, hyprctl dispatch togglefloating"

        # clipboard manager
        "$mainMod, V, exec, cliphist list | rofi -dmenu -theme-str 'window {width: 50%;} listview {columns: 1;}' | cliphist decode | wl-copy"
      ];
      source="~/.config/hypr/monitors.conf";
      # source="~/.config/hypr/workspaces.conf";
      # binds that repeat when held
      binde = [
        ",XF86AudioRaiseVolume,exec, pamixer -i 2"
        ",XF86AudioLowerVolume,exec, pamixer -d 2"
      ];
    };

    extraConfig = "
      monitor=,preferred,auto,1.2
      xwayland {
        force_zero_scaling = true
      }
    ";
  };
}
