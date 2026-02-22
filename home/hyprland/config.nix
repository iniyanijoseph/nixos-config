{ ... }:
let
  browser  = "firefox";
  terminal = "kitty";
  mail     = "thunderbird";
in
{
  wayland.windowManager.hyprland = {
    settings = {
      "$mainMod" = "SUPER";

      exec-once = [
        "swaybg -i /home/wug/Pictures/wallpaper.jpg &"
        "nm-applet &"
        "poweralertd &"
        "wl-clip-persist --clipboard both &"
        "wl-paste --watch cliphist store &"
        "swaync &"
        "hyprctl setcursor Bibata-Modern-Ice 24 &"
        "waybar"

        "[workspace 2 silent] ${browser}"
        "[workspace 3 silent] sleek-todo"
        "[workspace 1 silent] ${mail}"
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
        gaps_in = 6;
        gaps_out = 12;
        border_size = 2;
        "col.active_border" = "rgb(98971A) rgb(CC241D) 45deg";
        "col.inactive_border" = "0x00000000";
      };

      binds = {
        movefocus_cycles_fullscreen = true;
      };

      bind = [
        # Core — too frequent to go through a menu
        "$mainMod, Return, exec, ${terminal}"
        "$mainMod, Q, killactive,"
        "$mainMod, D, exec, rofi -show drun || pkill rofi"
        "$mainMod, Escape, exec, swaylock"
        "$mainMod, Space, exec, wlr-which-key"

        # Screenshot — Print stays as a direct bind
        ",Print, exec, grimblast --copy screen"
        "$mainMod SHIFT, S, exec, grimblast --freeze copy area"

        # Arrow key focus — kept for when hands are off home row
        "$mainMod, left,  movefocus, l"
        "$mainMod, right, movefocus, r"
        "$mainMod, up,    movefocus, u"
        "$mainMod, down,  movefocus, d"
        "$mainMod, L,  movefocus, l"
        "$mainMod, H, movefocus, r"
        "$mainMod, K,    movefocus, u"
        "$mainMod, J,  movefocus, d"

        # Arrow key move window
        "$mainMod SHIFT, left,  movewindow, l"
        "$mainMod SHIFT, right, movewindow, r"
        "$mainMod SHIFT, up,    movewindow, u"
        "$mainMod SHIFT, down,  movewindow, d"

        # Arrow key resize
        "$mainMod CTRL, left,  resizeactive, -80 0"
        "$mainMod CTRL, right, resizeactive, 80 0"
        "$mainMod CTRL, up,    resizeactive, 0 -80"
        "$mainMod CTRL, down,  resizeactive, 0 80"

        # Workspace switching — number keys are fastest, keep direct
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

        "$mainMod SHIFT, 1, movetoworkspacesilent, 1"
        "$mainMod SHIFT, 2, movetoworkspacesilent, 2"
        "$mainMod SHIFT, 3, movetoworkspacesilent, 3"
        "$mainMod SHIFT, 4, movetoworkspacesilent, 4"
        "$mainMod SHIFT, 5, movetoworkspacesilent, 5"
        "$mainMod SHIFT, 6, movetoworkspacesilent, 6"
        "$mainMod SHIFT, 7, movetoworkspacesilent, 7"
        "$mainMod SHIFT, 8, movetoworkspacesilent, 8"
        "$mainMod SHIFT, 9, movetoworkspacesilent, 9"
        "$mainMod, 0, workspace, 10"
        "$mainMod SHIFT, 0, movetoworkspacesilent, 10"

        # Media keys
        ",XF86AudioPlay, exec, playerctl play-pause"
        ",XF86AudioNext, exec, playerctl next"
        ",XF86AudioPrev, exec, playerctl previous"
        ",XF86AudioStop, exec, playerctl stop"

        # Special keyboard keys
        ",code:235, exec, nwg-displays"
        ",code:152, exec, nwg-displays"
        ",code:163, exec, ${mail}"
        ",code:452, exec, ${mail}"
        ",code:453, exec, blueman-manager"
        ",code:454, exec, ${browser}"
        ",code:256, exec, pavucontrol"
        ",code:179, exec, pavucontrol"
        ",code:164, exec, ${terminal} yazi"
        ",code:148, exec, ${terminal} yazi"
        ",code:180, exec, ${browser}"

        "$mainMod, mouse_down, workspace, e-1"
        "$mainMod, mouse_up,   workspace, e+1"
      ];

      source = "~/.config/hypr/monitors.conf";

      binde = [
        ",XF86AudioRaiseVolume, exec, pamixer -i 2"
        ",XF86AudioLowerVolume, exec, pamixer -d 2"
        ",XF86MonBrightnessUp,   exec, brightnessctl set 5%+"
        ",XF86MonBrightnessDown, exec, brightnessctl set 5%-"
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
