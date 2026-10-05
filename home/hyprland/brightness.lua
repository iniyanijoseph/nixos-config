-- Correct SwayOSD brightness bindings. The main desktop config historically
-- used invalid extra arguments ("raise 5%+" / "lower 5%-"). Unbind those
-- first, then register current SwayOSD syntax with repeat-on-hold.
pcall(function()
    hl.unbind("XF86MonBrightnessUp")
    hl.unbind("XF86MonBrightnessDown")

    local opts = { locked = true, repeating = true }
    hl.bind(
        "XF86MonBrightnessUp",
        hl.dsp.exec_cmd("swayosd-client --brightness +5"),
        opts
    )
    hl.bind(
        "XF86MonBrightnessDown",
        hl.dsp.exec_cmd("swayosd-client --brightness -5"),
        opts
    )
end)
