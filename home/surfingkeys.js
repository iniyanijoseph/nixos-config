// Small, conservative Surfingkeys layer on top of the defaults.

// Do not let pages steal the keyboard into an input on load.
settings.stealFocusOnLoad = true;
settings.enableAutoFocus = false;

// Directional browsing.
// Surfingkeys defaults already use j/k for down/up.
api.unmap("h");
api.unmap("l");
api.mapkey("h", "Scroll right", function() {
    api.Normal.scroll("right");
});
api.mapkey("l", "Scroll left", function() {
    api.Normal.scroll("left");
});

// Browser history.
api.map("H", "D"); // forward
api.map("L", "S"); // back

// Tabs.
api.map("J", "R"); // next tab
api.map("K", "E"); // previous tab

// Links.
api.map("F", "af"); // open link in an active new tab

// Gruvbox Dark Hard + green accent.
settings.theme = `
.sk_theme {
    font-family: "Maple Mono", "JetBrainsMono Nerd Font", monospace;
    font-size: 11pt;
    background: #1d2021;
    color: #ebdbb2;
    border: 1px solid #504945;
}
.sk_theme tbody,
.sk_theme input {
    color: #ebdbb2;
}
.sk_theme input {
    background: #282828;
    border: 1px solid #504945;
}
.sk_theme .url {
    color: #8ec07c;
}
.sk_theme .annotation {
    color: #b8bb26;
}
.sk_theme .omnibar_highlight {
    color: #fabd2f;
}
.sk_theme .omnibar_timestamp {
    color: #d3869b;
}
.sk_theme .omnibar_visitcount {
    color: #83a598;
}
.sk_theme #sk_omnibarSearchResult ul li:nth-child(odd) {
    background: #282828;
}
.sk_theme #sk_omnibarSearchResult ul li.focused {
    background: #3c3836;
    color: #fbf1c7;
}
#sk_status,
#sk_find {
    font-family: "Maple Mono", "JetBrainsMono Nerd Font", monospace;
    background: #1d2021;
    color: #ebdbb2;
    border: 1px solid #504945;
}
`;
