-- Startup-only application routing that is awkward to express as static rules.
-- Keep this separate from the main desktop config so session-restoration logic
-- does not affect ordinary window placement later in the session.

local firefoxClass = "^(firefox|Firefox)$"
local cinnyClass = "^(cinny|Cinny|cinny-desktop|in\\.cinny\\.app)$"

local function cinnyRule(name, match)
    hl.window_rule({
        name = name,
        match = match,
        workspace = "1",
        float = false,
        tile = true,
        fullscreen = false,
        maximize = false,
        fullscreen_state = "0 0",
        suppress_event = "fullscreen maximize",
    })
end

pcall(function()
    -- cinny-desktop is included explicitly because Tauri/WebKit builds can
    -- expose either the product name, binary name, or application identifier
    -- as the initial Wayland class/app-id.
    cinnyRule("cinny-workspace-fallback", { class = cinnyClass })
    cinnyRule("cinny-title-fallback", { title = "^Cinny$" })

    -- Static fast-path for a restored Firefox window whose initial selected
    -- tab is already YouTube Music.
    hl.window_rule({
        name = "youtube-music-startup-workspace",
        match = {
            class = firefoxClass,
            title = ".*YouTube Music.*",
        },
        workspace = "10",
    })
end)

local startupMusicRouting = false
local startupMusicTimer = nil

local function routeYouTubeMusicWindow(w)
    if not startupMusicRouting or w == nil then
        return
    end

    local class = string.lower(w.class or "")
    local title = string.lower(w.title or "")

    if class == "firefox" and string.find(title, "youtube music", 1, true) then
        pcall(function()
            hl.dispatch(hl.dsp.window.move({
                window = w,
                workspace = 10,
                follow = false,
            }))
        end)
    end
end

-- Firefox session restore often assigns the real tab title shortly after the
-- native window is mapped, so watch both creation and title changes during the
-- first minute of the desktop session.
pcall(hl.on, "window.open", routeYouTubeMusicWindow)
pcall(hl.on, "window.title", routeYouTubeMusicWindow)

pcall(hl.on, "hyprland.start", function()
    startupMusicRouting = true

    -- Do not depend on Cinny's restored state or class matching for its initial
    -- placement: ask Hyprland to launch the process directly on workspace 1.
    pcall(hl.exec_cmd, "cinny", { workspace = "1 silent" })

    startupMusicTimer = hl.timer(function()
        startupMusicRouting = false
    end, {
        timeout = 60000,
        type = "oneshot",
    })
end)
