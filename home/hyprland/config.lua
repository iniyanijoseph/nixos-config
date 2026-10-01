local browser = "firefox"
local terminal = "kitty"
local mail = "thunderbird"
local mainMod = "SUPER"

-- Use an unscaled fallback when nwg-displays has not produced a rule yet.
-- Its exact output rules are loaded afterward and take precedence.
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1.0 })
local configHome = os.getenv("XDG_CONFIG_HOME") or (os.getenv("HOME") .. "/.config")
pcall(dofile, configHome .. "/hypr/monitors.lua")
pcall(dofile, configHome .. "/hypr/workspaces.lua")

-- Keep a bad appearance option from preventing every keybinding below from
-- being registered. Hyprland reports the offending option in config errors.
pcall(hl.config, {
    input = {
        numlock_by_default = true,
        repeat_delay = 300,
        follow_mouse = 1,
        float_switch_override_focus = 0,
        mouse_refocus = true,

        -- Use libinput's device-aware adaptive curve, but keep it milder than
        -- the previous +0.35 setting. A flat profile felt heavy/laggy because
        -- it removed the velocity ramp entirely.
        accel_profile = "adaptive",
        force_no_accel = false,
        sensitivity = 0.15,
    },
    cursor = {
        -- Prefer a hardware cursor instead of Hyprland's auto switching.
        -- This keeps pointer presentation independent of normal scene redraws
        -- when the DRM backend supports a cursor plane.
        no_hardware_cursors = 0,
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
        gaps_in = 3,
        gaps_out = 6,
        border_size = 2,
        col = {
            active_border = {
                colors = { "rgb(98971A)", "rgb(CC241D)" },
                angle = 45,
            },
            inactive_border = "rgba(00000000)",
        },
    },
    animations = { enabled = true },
    binds = { movefocus_cycles_fullscreen = true },
    xwayland = { force_zero_scaling = true },
})

-- Cinny's Linux window class is normally "cinny" (the Tauri bundle id
-- can also appear on some builds). Ignore its startup maximize/fullscreen
-- request and force the initial compositor/client fullscreen state to none.
pcall(function()
    hl.window_rule({
        name = "cinny-start-tiled",
        match = { class = "^(cinny|Cinny|in\\.cinny\\.app)$" },
        tile = true,
        fullscreen = false,
        maximize = false,
        fullscreen_state = "0 0",
        suppress_event = "fullscreen maximize",
    })
end)

-- Be defensive against Cinny changing/advertising its class after mapping:
-- once the fully initialized window opens, explicitly put it back in the
-- normal tiled/non-fullscreen state. This runs only at window creation, so
-- later user-requested fullscreen/maximize still works normally.
pcall(hl.on, "window.open", function(w)
    local class = string.lower(w.class or "")
    local title = string.lower(w.title or "")
    if class ~= "cinny" and class ~= "in.cinny.app" and title ~= "cinny" then
        return
    end

    pcall(function()
        hl.dispatch(hl.dsp.window.float({ action = "unset", window = w }))
        hl.dispatch(hl.dsp.window.fullscreen_state({
            internal = 0,
            client = 0,
            action = "set",
            layout_aware = false,
            window = w,
        }))
    end)
end)

pcall(function()
    hl.curve("quick", {
        type = "bezier",
        points = { { 0.2, 0.8 }, { 0.2, 1.0 } },
    })
    hl.animation({ leaf = "windows", enabled = true, speed = 2.5, bezier = "quick" })
    hl.animation({ leaf = "windowsOut", enabled = true, speed = 2, bezier = "quick", style = "popin 80%" })
    hl.animation({ leaf = "border", enabled = true, speed = 2, bezier = "quick" })
    hl.animation({ leaf = "fade", enabled = true, speed = 2, bezier = "quick" })
    hl.animation({ leaf = "workspaces", enabled = true, speed = 2.5, bezier = "quick", style = "slide" })
end)

pcall(hl.on, "hyprland.start", function()
    pcall(hl.exec_cmd, "swaybg -i /home/wug/Pictures/wallpaper.jpg")
    pcall(hl.exec_cmd, "nm-applet")
    pcall(hl.exec_cmd, "poweralertd")
    pcall(hl.exec_cmd, "wl-clip-persist --clipboard both")
    pcall(hl.exec_cmd, "wl-paste --watch cliphist store")
    pcall(hl.exec_cmd, "swaync")
    pcall(hl.exec_cmd, "swayosd-server")
    pcall(hl.exec_cmd, "hyprctl setcursor Bibata-Modern-Ice 24")
    pcall(hl.exec_cmd, "waybar")
    pcall(hl.exec_cmd, browser, { workspace = "2 silent" })
    pcall(hl.exec_cmd, mail, { workspace = "1 silent" })
end)

local function run(key, command, options)
    pcall(function()
        hl.bind(key, hl.dsp.exec_cmd(command), options)
    end)
end

local function focus(key, direction)
    pcall(function()
        hl.bind(mainMod .. " + " .. key, hl.dsp.focus({ direction = direction }))
    end)
end

local function move(key, direction)
    pcall(function()
        hl.bind(mainMod .. " + SHIFT + " .. key, hl.dsp.window.move({ direction = direction }))
    end)
end

local function resize(key, x, y)
    pcall(function()
        hl.bind(mainMod .. " + CTRL + " .. key, hl.dsp.window.resize({
            x = x,
            y = y,
            relative = true,
        }))
    end)
end

run(mainMod .. " + Return", terminal)
pcall(function()
    hl.bind(mainMod .. " + Q", hl.dsp.window.close())
end)
run(mainMod .. " + D", "rofi -show drun || pkill rofi")
run(mainMod .. " + Escape", "swaylock")
run(mainMod .. " + N", "swaync-client -t -sw")
run(mainMod .. " + Space", "wlr-which-key")
run("Print", "grimblast --copy screen")
run(mainMod .. " + SHIFT + S", "grimblast --freeze copy area")

-- Directional navigation: h = right, l = left, j = down, k = up.
focus("left", "left")
focus("right", "right")
focus("up", "up")
focus("down", "down")
focus("L", "left")
focus("H", "right")
focus("K", "up")
focus("J", "down")

move("L", "left")
move("H", "right")
move("K", "up")
move("J", "down")
move("left", "left")
move("right", "right")
move("up", "up")
move("down", "down")

resize("L", -80, 0)
resize("H", 80, 0)
resize("K", 0, -80)
resize("J", 0, 80)
resize("left", -80, 0)
resize("right", 80, 0)
resize("up", 0, -80)
resize("down", 0, 80)

for workspace = 1, 10 do
    local key = workspace % 10
    pcall(function()
        hl.bind(mainMod .. " + " .. key, hl.dsp.focus({ workspace = workspace }))
        hl.bind(mainMod .. " + SHIFT + " .. key, hl.dsp.window.move({
            workspace = workspace,
            follow = false,
        }))
    end)
end

run("XF86AudioPlay", "playerctl play-pause")
run("XF86AudioNext", "playerctl next")
run("XF86AudioPrev", "playerctl previous")
run("XF86AudioStop", "playerctl stop")
run("code:235", "nwg-displays")
run("code:152", "nwg-displays")
run("code:163", mail)
run("code:452", mail)
run("code:453", "blueman-manager")
run("code:454", browser)
run("code:256", "pavucontrol")
run("code:179", "pavucontrol")
run("code:164", terminal .. " yazi")
run("code:148", terminal .. " yazi")
run("code:180", browser)

pcall(function()
    hl.bind(mainMod .. " + mouse_down", hl.dsp.focus({ workspace = "e-1" }))
    hl.bind(mainMod .. " + mouse_up", hl.dsp.focus({ workspace = "e+1" }))
end)

-- SwayOSD media, brightness, and lock-key feedback. These preserve the old
-- bindl/bindle/bindr behavior using native Lua binding flags.
local lockedOptions = { locked = true }
local lockedRepeatOptions = { locked = true, repeating = true }
local releaseOptions = { release = true }
run("XF86AudioMute", "swayosd-client --output-volume mute-toggle")
run("XF86MonBrightnessUp", "swayosd-client --brightness raise 5%+", lockedOptions)
run("XF86MonBrightnessDown", "swayosd-client --brightness lower 5%-", lockedOptions)
run(mainMod .. " + XF86MonBrightnessUp", "brightnessctl set 100%", lockedOptions)
run(mainMod .. " + XF86MonBrightnessDown", "brightnessctl set 0%", lockedOptions)
run("XF86AudioRaiseVolume", "swayosd-client --output-volume +2 --max-volume=100", lockedRepeatOptions)
run("XF86AudioLowerVolume", "swayosd-client --output-volume -2", lockedRepeatOptions)
run(mainMod .. " + f11", "swayosd-client --output-volume +2 --max-volume=100", lockedRepeatOptions)
run(mainMod .. " + f12", "swayosd-client --output-volume -2", lockedRepeatOptions)
run("CAPS + Caps_Lock", "swayosd-client --caps-lock", releaseOptions)
run("Scroll_Lock", "swayosd-client --scroll-lock", releaseOptions)
run("Num_Lock", "swayosd-client --num-lock", releaseOptions)

