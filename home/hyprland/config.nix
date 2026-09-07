{ ... }:
{
  wayland.windowManager.hyprland.extraConfig = ''
    local browser = "firefox"
    local terminal = "kitty"
    local mail = "thunderbird"
    local mainMod = "SUPER"

    -- nwg-displays 0.4.3+ writes monitors.lua. Prefer it, while importing the
    -- existing monitors.conf once so this migration keeps the current layout.
    -- Home Manager's config is a store symlink, so explicitly include the
    -- user config directory in Lua's module search path.
    local hyprConfigDir = os.getenv("HOME") .. "/.config/hypr"
    package.path = hyprConfigDir .. "/?.lua;" .. hyprConfigDir .. "/?/init.lua;" .. package.path
    local monitorsLoaded = pcall(require, "monitors")

    if not monitorsLoaded then
      local monitorFile = io.open(hyprConfigDir .. "/monitors.conf", "r")

      if monitorFile then
        for line in monitorFile:lines() do
          local spec = line:match("^%s*monitor%s*=%s*(.-)%s*$")
          if spec then
            local fields = {}
            for field in (spec .. ","):gmatch("(.-),") do
              table.insert(fields, field)
            end

            if fields[2] == "disable" then
              hl.monitor({ output = fields[1], disabled = true })
            elseif fields[2] == "transform" and fields[3] then
              -- Older nwg-displays versions wrote transforms as a second rule.
              hl.monitor({ output = fields[1], transform = tonumber(fields[3]) })
            elseif fields[2] and fields[3] and fields[4] then
              local monitor = {
                output = fields[1],
                mode = fields[2],
                position = fields[3],
                scale = tonumber(fields[4]) or fields[4],
              }

              local index = 5
              while fields[index] do
                local property = fields[index]
                local value = fields[index + 1]
                if property == "mirror" then
                  monitor.mirror = value
                elseif property == "transform" then
                  monitor.transform = tonumber(value)
                elseif property == "bitdepth" then
                  monitor.bitdepth = tonumber(value)
                elseif property == "cm" then
                  monitor.cm = value
                elseif property == "sdrbrightness" then
                  monitor.sdrbrightness = tonumber(value)
                elseif property == "sdrsaturation" then
                  monitor.sdrsaturation = tonumber(value)
                elseif property == "vrr" then
                  monitor.vrr = tonumber(value)
                end
                index = index + 2
              end

              hl.monitor(monitor)
            end
          end
        end
        monitorFile:close()
      end
    end

    -- Preserve the old fallback for displays not covered by nwg-displays. A
    -- connector-specific rule above takes precedence over this wildcard.
    hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1.2 })

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

    hl.bind(mainMod .. " + RETURN", hl.dsp.exec_cmd(terminal))
    hl.bind(mainMod .. " + Q", hl.dsp.window.close())
    hl.bind(mainMod .. " + D", hl.dsp.exec_cmd("rofi -show drun || pkill rofi"))
    hl.bind(mainMod .. " + ESCAPE", hl.dsp.exec_cmd("swaylock"))
    hl.bind(mainMod .. " + SPACE", hl.dsp.exec_cmd("wlr-which-key"))
    hl.bind("PRINT", hl.dsp.exec_cmd("grimblast --copy screen"))
    hl.bind(mainMod .. " + SHIFT + S", hl.dsp.exec_cmd("grimblast --freeze copy area"))

    hl.bind(mainMod .. " + left", hl.dsp.focus({ direction = "left" }))
    hl.bind(mainMod .. " + right", hl.dsp.focus({ direction = "right" }))
    hl.bind(mainMod .. " + up", hl.dsp.focus({ direction = "up" }))
    hl.bind(mainMod .. " + down", hl.dsp.focus({ direction = "down" }))
    -- Preserve the original home-row layout (L=left and H=right).
    hl.bind(mainMod .. " + L", hl.dsp.focus({ direction = "left" }))
    hl.bind(mainMod .. " + H", hl.dsp.focus({ direction = "right" }))
    hl.bind(mainMod .. " + K", hl.dsp.focus({ direction = "up" }))
    hl.bind(mainMod .. " + J", hl.dsp.focus({ direction = "down" }))

    hl.bind(mainMod .. " + SHIFT + left", hl.dsp.window.move({ direction = "left" }))
    hl.bind(mainMod .. " + SHIFT + right", hl.dsp.window.move({ direction = "right" }))
    hl.bind(mainMod .. " + SHIFT + up", hl.dsp.window.move({ direction = "up" }))
    hl.bind(mainMod .. " + SHIFT + down", hl.dsp.window.move({ direction = "down" }))

    hl.bind(mainMod .. " + CTRL + left",
      hl.dsp.window.resize({ x = -80, y = 0, relative = true }), { repeating = true })
    hl.bind(mainMod .. " + CTRL + right",
      hl.dsp.window.resize({ x = 80, y = 0, relative = true }), { repeating = true })
    hl.bind(mainMod .. " + CTRL + up",
      hl.dsp.window.resize({ x = 0, y = -80, relative = true }), { repeating = true })
    hl.bind(mainMod .. " + CTRL + down",
      hl.dsp.window.resize({ x = 0, y = 80, relative = true }), { repeating = true })

    hl.bind(mainMod .. " + 1", hl.dsp.focus({ workspace = 1 }))
    hl.bind(mainMod .. " + 2", hl.dsp.focus({ workspace = 2 }))
    hl.bind(mainMod .. " + 3", hl.dsp.focus({ workspace = 3 }))
    hl.bind(mainMod .. " + 4", hl.dsp.focus({ workspace = 4 }))
    hl.bind(mainMod .. " + 5", hl.dsp.focus({ workspace = 5 }))
    hl.bind(mainMod .. " + 6", hl.dsp.focus({ workspace = 6 }))
    hl.bind(mainMod .. " + 7", hl.dsp.focus({ workspace = 7 }))
    hl.bind(mainMod .. " + 8", hl.dsp.focus({ workspace = 8 }))
    hl.bind(mainMod .. " + 9", hl.dsp.focus({ workspace = 9 }))
    hl.bind(mainMod .. " + 0", hl.dsp.focus({ workspace = 10 }))

    hl.bind(mainMod .. " + SHIFT + 1", hl.dsp.window.move({ workspace = 1, follow = false }))
    hl.bind(mainMod .. " + SHIFT + 2", hl.dsp.window.move({ workspace = 2, follow = false }))
    hl.bind(mainMod .. " + SHIFT + 3", hl.dsp.window.move({ workspace = 3, follow = false }))
    hl.bind(mainMod .. " + SHIFT + 4", hl.dsp.window.move({ workspace = 4, follow = false }))
    hl.bind(mainMod .. " + SHIFT + 5", hl.dsp.window.move({ workspace = 5, follow = false }))
    hl.bind(mainMod .. " + SHIFT + 6", hl.dsp.window.move({ workspace = 6, follow = false }))
    hl.bind(mainMod .. " + SHIFT + 7", hl.dsp.window.move({ workspace = 7, follow = false }))
    hl.bind(mainMod .. " + SHIFT + 8", hl.dsp.window.move({ workspace = 8, follow = false }))
    hl.bind(mainMod .. " + SHIFT + 9", hl.dsp.window.move({ workspace = 9, follow = false }))
    hl.bind(mainMod .. " + SHIFT + 0", hl.dsp.window.move({ workspace = 10, follow = false }))

    hl.bind("XF86AudioPlay", hl.dsp.exec_cmd("playerctl play-pause"))
    hl.bind("XF86AudioNext", hl.dsp.exec_cmd("playerctl next"))
    hl.bind("XF86AudioPrev", hl.dsp.exec_cmd("playerctl previous"))
    hl.bind("XF86AudioStop", hl.dsp.exec_cmd("playerctl stop"))

    hl.bind("code:235", hl.dsp.exec_cmd("nwg-displays"))
    hl.bind("code:152", hl.dsp.exec_cmd("nwg-displays"))
    hl.bind("code:163", hl.dsp.exec_cmd(mail))
    hl.bind("code:452", hl.dsp.exec_cmd(mail))
    hl.bind("code:453", hl.dsp.exec_cmd("blueman-manager"))
    hl.bind("code:454", hl.dsp.exec_cmd(browser))
    hl.bind("code:256", hl.dsp.exec_cmd("pavucontrol"))
    hl.bind("code:179", hl.dsp.exec_cmd("pavucontrol"))
    hl.bind("code:164", hl.dsp.exec_cmd(terminal .. " yazi"))
    hl.bind("code:148", hl.dsp.exec_cmd(terminal .. " yazi"))
    hl.bind("code:180", hl.dsp.exec_cmd(browser))

    hl.bind(mainMod .. " + mouse_down", hl.dsp.focus({ workspace = "e-1" }))
    hl.bind(mainMod .. " + mouse_up", hl.dsp.focus({ workspace = "e+1" }))

    -- These repeating bindings existed alongside the swayosd bindings before
    -- the Lua migration; retain them for an exact keymap migration.
    hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("pamixer -i 2"), { repeating = true })
    hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("pamixer -d 2"), { repeating = true })
    hl.bind("XF86MonBrightnessUp", hl.dsp.exec_cmd("brightnessctl set 5%+"), { repeating = true })
    hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl set 5%-"), { repeating = true })
  '';
}
