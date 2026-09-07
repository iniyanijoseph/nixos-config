{ pkgs, ... }:
{
  home.packages = with pkgs; [ swayosd ];

  wayland.windowManager.hyprland.extraConfig = ''
    hl.on("hyprland.start", function()
      hl.exec_cmd("swayosd-server")
    end)

    local function osdCommand(key, cmd, options)
      hl.bind(key, hl.dsp.exec_cmd(cmd), options)
    end

    osdCommand("XF86AudioMute", "swayosd-client --output-volume mute-toggle")

    -- These remain active while the screen is locked.
    osdCommand("XF86MonBrightnessUp", "swayosd-client --brightness raise 5%+", { locked = true })
    osdCommand("XF86MonBrightnessDown", "swayosd-client --brightness lower 5%-", { locked = true })
    osdCommand("SUPER + XF86MonBrightnessUp", "brightnessctl set 100%", { locked = true })
    osdCommand("SUPER + XF86MonBrightnessDown", "brightnessctl set 0%", { locked = true })

    osdCommand("XF86AudioRaiseVolume", "swayosd-client --output-volume +2 --max-volume=100",
      { locked = true, repeating = true })
    osdCommand("XF86AudioLowerVolume", "swayosd-client --output-volume -2",
      { locked = true, repeating = true })
    osdCommand("SUPER + F11", "swayosd-client --output-volume +2 --max-volume=100",
      { locked = true, repeating = true })
    osdCommand("SUPER + F12", "swayosd-client --output-volume -2",
      { locked = true, repeating = true })

    osdCommand("CAPS_LOCK", "swayosd-client --caps-lock", { release = true })
    osdCommand("SCROLL_LOCK", "swayosd-client --scroll-lock", { release = true })
    osdCommand("NUM_LOCK", "swayosd-client --num-lock", { release = true })
  '';

  xdg.configFile."swayosd/style.css".text = ''
    window {
        padding: 0px 10px;
        border-radius: 25px;
        border: 10px;
        background: alpha(#282828, 0.99);
    }

    #container {
        margin: 15px;
    }

    image, label {
        color: #FBF1C7;
    }

    progressbar:disabled,
    image:disabled {
        opacity: 0.95;
    }

    progressbar {
        min-height: 6px;
        border-radius: 999px;
        background: transparent;
        border: none;
    }
    trough {
        min-height: inherit;
        border-radius: inherit;
        border: none;
        background: alpha(#DDDDDD, 0.2);
    }
    progress {
        min-height: inherit;
        border-radius: inherit;
        border: none;
        background: #FBF1C7;
    }
  '';
}
