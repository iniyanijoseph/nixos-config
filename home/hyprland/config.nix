{ ... }:
{
  wayland.windowManager.hyprland.extraConfig = ''
    local browser = "firefox"
    local terminal = "kitty"
    local mail = "thunderbird"
    local mainMod = "SUPER"

    -- A generic monitor rule replaces the generated monitors.conf include.
    hl.monitor({
      output = "",
      mode = "preferred",
      position = "auto",
      scale = 1.2,
    })

    hl.config({
      input = {
        numlock_by_default = true,
        repeat_delay = 300,
        follow_mouse = 0,
        float_switch_override_focus = 0,
        mouse_refocus = false,
        sensitivity = 0,
      },
      decoration = {
        rounding = 0,
        active_opacity = 1.0,
        inactive_opacity = 0.90,
        fullscreen_opacity = 1.0,
        blur = {
          enabled = true,
          size = 3,
          passes = 2,
          brightness = 1,
          contrast = 1.4,
          ignore_opacity = true,
          noise = 0,
          new_optimizations = true,
          xray = true,
        },
        shadow = {
          enabled = true,
          offset = { 0, 2 },
          range = 20,
          render_power = 3,
          color = "rgba(00000055)",
        },
      },
      general = {
        gaps_in = 6,
        gaps_out = 12,
        border_size = 2,
        col = {
          active_border = {
            colors = { "rgb(98971A)", "rgb(CC241D)" },
            angle = 45,
          },
          inactive_border = "rgba(00000000)",
        },
      },
      binds = {
        movefocus_cycles_fullscreen = true,
      },
      xwayland = {
        force_zero_scaling = true,
      },
    })

    hl.on("hyprland.start", function()
      hl.exec_cmd("swaybg -i /home/wug/Pictures/wallpaper.jpg")
      hl.exec_cmd("nm-applet")
      hl.exec_cmd("poweralertd")
      hl.exec_cmd("wl-clip-persist --clipboard both")
      hl.exec_cmd("wl-paste --watch cliphist store")
      hl.exec_cmd("swaync")
      hl.exec_cmd("hyprctl setcursor Bibata-Modern-Ice 24")
      hl.exec_cmd("waybar")
      hl.exec_cmd(browser, { workspace = "2 silent" })
      hl.exec_cmd(mail, { workspace = "1 silent" })
    end)

    local function command(key, cmd, options)
      hl.bind(key, hl.dsp.exec_cmd(cmd), options)
    end

    command(mainMod .. " + RETURN", terminal)
    hl.bind(mainMod .. " + Q", hl.dsp.window.close())
    command(mainMod .. " + D", "rofi -show drun || pkill rofi")
    command(mainMod .. " + ESCAPE", "swaylock")
    command(mainMod .. " + SPACE", "wlr-which-key")
    command("PRINT", "grimblast --copy screen")
    command(mainMod .. " + SHIFT + S", "grimblast --freeze copy area")

    for _, binding in ipairs({
      { "left", "left" }, { "right", "right" },
      { "up", "up" }, { "down", "down" },
      -- Preserve the existing home-row layout (H=right, L=left).
      { "L", "left" }, { "H", "right" }, { "K", "up" }, { "J", "down" },
    }) do
      hl.bind(mainMod .. " + " .. binding[1], hl.dsp.focus({ direction = binding[2] }))
    end

    for _, binding in ipairs({
      { "left", "left" }, { "right", "right" },
      { "up", "up" }, { "down", "down" },
    }) do
      hl.bind(mainMod .. " + SHIFT + " .. binding[1],
        hl.dsp.window.move({ direction = binding[2] }))
    end

    for _, binding in ipairs({
      { "left", -80, 0 }, { "right", 80, 0 },
      { "up", 0, -80 }, { "down", 0, 80 },
    }) do
      hl.bind(mainMod .. " + CTRL + " .. binding[1],
        hl.dsp.window.resize({ x = binding[2], y = binding[3], relative = true }),
        { repeating = true })
    end

    for workspace = 1, 10 do
      local key = workspace % 10
      hl.bind(mainMod .. " + " .. key, hl.dsp.focus({ workspace = workspace }))
      hl.bind(mainMod .. " + SHIFT + " .. key,
        hl.dsp.window.move({ workspace = workspace, follow = false }))
    end

    command("XF86AudioPlay", "playerctl play-pause", { locked = true })
    command("XF86AudioNext", "playerctl next", { locked = true })
    command("XF86AudioPrev", "playerctl previous", { locked = true })
    command("XF86AudioStop", "playerctl stop", { locked = true })

    command("code:163", mail)
    command("code:452", mail)
    command("code:453", "blueman-manager")
    command("code:454", browser)
    command("code:256", "pavucontrol")
    command("code:179", "pavucontrol")
    command("code:164", terminal .. " yazi")
    command("code:148", terminal .. " yazi")
    command("code:180", browser)

    hl.bind(mainMod .. " + mouse_down", hl.dsp.focus({ workspace = "e-1" }))
    hl.bind(mainMod .. " + mouse_up", hl.dsp.focus({ workspace = "e+1" }))
  '';
}
