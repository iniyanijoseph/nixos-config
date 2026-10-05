{ pkgs, ... }:
{
  # SwayOSD ships udev rules for backlight devices. Include them system-wide
  # and give the desktop user the group those rules use for brightness writes.
  services.udev.packages = [ pkgs.swayosd ];
  users.users.wug.extraGroups = [ "video" ];
}
