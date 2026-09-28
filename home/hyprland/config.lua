local browser = "firefox"
local terminal = "kitty"
local mail = "thunderbird"
local mainMod = "SUPER"

-- nwg-displays' exact output rules are loaded after this new-machine fallback
-- and therefore take precedence over the wildcard.
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1.2 })
if package.searchpath("monitors", package.path) then
    require("monitors")
end
if package.searchpath("workspaces", package.path) then
    require("workspaces")
end

hl.config({
    input = {
        numlock_by_default = true,
        repeat_delay = 300,
        follow_mouse = 1,
        float_switch_override_focus = 0,
        mouse_refocus = true,
        sensitivity = 0.35,
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

hl.curve("quick", {
    type = "bezier",
    points = { { 0.2, 0.8 }, { 0.2, 1.0 } },
})
hl.animation({ leaf = "windows", enabled = true, speed = 2.5, bezier = "quick" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 2, bezier = "quick", style = "popin 80%" })
hl.animation({ leaf = "border", enabled = true, speed = 2, bezier = "quick" })
hl.animation({ leaf = "fade", enabled = true, speed = 2, bezier = "quick" })
hl.animation({ leaf = "workspaces", enabled = true, speed = 2.5, bezier = "quick", style = "slide" })

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

local function run(key, command, options)
    hl.bind(key, hl.dsp.exec_cmd(command), options)
end

local function focus(key, direction)
    hl.bind(mainMod .. " + " .. key, hl.dsp.focus({ direction = direction }))
end

local function move(key, direction)
    hl.bind(mainMod .. " + SHIFT + " .. key, hl.dsp.window.move({ direction = direction }))
end

local function resize(key, x, y)
    hl.bind(mainMod .. " + CTRL + " .. key, hl.dsp.window.resize({
        x = x,
        y = y,
        relative = true,
    }))
end

run(mainMod .. " + Return", terminal)
hl.bind(mainMod .. " + Q", hl.dsp.window.close())
run(mainMod .. " + D", "rofi -show drun || pkill rofi")
run(mainMod .. " + Escape", "swaylock")
run(mainMod .. " + N", "swaync-client -t -sw")
run(mainMod .. " + Space", "wlr-which-key")
run("Print", "grimblast --copy screen")
run(mainMod .. " + SHIFT + S", "grimblast --freeze copy area")

-- Helix navigation: h = right, l = left, j = down, k = up.
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
    hl.bind(mainMod .. " + " .. key, hl.dsp.focus({ workspace = workspace }))
    hl.bind(mainMod .. " + SHIFT + " .. key, hl.dsp.window.move({
        workspace = workspace,
        follow = false,
    }))
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

hl.bind(mainMod .. " + mouse_down", hl.dsp.focus({ workspace = "e-1" }))
hl.bind(mainMod .. " + mouse_up", hl.dsp.focus({ workspace = "e+1" }))

local repeatOptions = { repeating = true }
run("XF86AudioRaiseVolume", "pamixer -i 2", repeatOptions)
run("XF86AudioLowerVolume", "pamixer -d 2", repeatOptions)
run("XF86MonBrightnessUp", "brightnessctl set 5%+", repeatOptions)
run("XF86MonBrightnessDown", "brightnessctl set 5%-", repeatOptions)

hl.window_rule({
    name = "kitty-floating",
    match = { class = "^kitty$" },
    float = true,
    size = { "monitor_w*0.8", "monitor_h*0.8" },
    center = true,
})
