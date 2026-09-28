// Keep Firefox navigation aligned with the system's Helix direction map:
// h = right, l = left, j = down, k = up.
api.unmap("h");
api.unmap("l");
api.unmap("j");
api.unmap("k");

api.mapkey("h", "Scroll right (Helix)", () => api.Normal.scroll("right"));
api.mapkey("l", "Scroll left (Helix)", () => api.Normal.scroll("left"));
api.mapkey("j", "Scroll down (Helix)", () => api.Normal.scroll("down"));
api.mapkey("k", "Scroll up (Helix)", () => api.Normal.scroll("up"));

// Surfingkeys already uses ? for its generated shortcut reference.
