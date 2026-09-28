// Keep the common Surfingkeys defaults and add a small set of easier aliases.
const { map, mapkey, unmap, Normal } = api;

// Scrolling.
unmap("h");
unmap("l");
mapkey("h", "Scroll right", () => Normal.scroll("right"));
mapkey("l", "Scroll left", () => Normal.scroll("left"));

// History: uppercase directions.
map("H", "D"); // forward
map("L", "S"); // back

// Tabs: uppercase vertical movement.
map("J", "R"); // next tab
map("K", "E"); // previous tab

// Links: f opens here; F opens in an active new tab.
map("F", "af");

// Hide the old, less mnemonic aliases from normal-mode help.
["S", "D", "E", "R"].forEach((key) => unmap(key));
