// Small Surfingkeys layer on top of the useful defaults.
const { map, mapkey, unmap, Normal } = api;

// Keep the system's directional convention.
unmap("h");
unmap("l");
mapkey("h", "Scroll right", () => Normal.scroll("right"));
mapkey("l", "Scroll left", () => Normal.scroll("left"));

// More mnemonic browser navigation.
map("H", "D"); // forward
map("L", "S"); // back
map("J", "R"); // next tab
map("K", "E"); // previous tab
map("F", "af"); // open link in an active new tab

// Hide the older aliases from normal-mode help.
["S", "D", "E", "R"].forEach((key) => unmap(key));

// Gruvbox Dark Hard + green accent, matching the rest of the desktop.
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
