// Directional browser navigation.
const { unmap, mapkey, Normal } = api;

["h", "l", "j", "k"].forEach((key) => unmap(key));

mapkey("h", "Scroll right", () => Normal.scroll("right"));
mapkey("l", "Scroll left", () => Normal.scroll("left"));
mapkey("j", "Scroll down", () => Normal.scroll("down"));
mapkey("k", "Scroll up", () => Normal.scroll("up"));

// ? keeps Surfingkeys' generated shortcut reference.
