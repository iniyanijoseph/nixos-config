{ pkgs, ... }:
{
  # Ripcord is a single non-Electron Qt client that covers Discord and
  # Slack. Free for Discord; Slack works unpaid too, just nags for a
  # license.
  home.packages = with pkgs; [ ripcord ];

  # zoom-us drags along a fair amount of local cache/log clutter under
  # ~/.zoom and ~/.config/zoomus.conf for what's usually occasional calls.
  # Zoom's web client covers joining/hosting fine - in your Zoom profile,
  # enable "Always use my browser when I click a join link" under
  # Settings > General to stop it from nagging you to install the app.
  xdg.desktopEntries.zoom-web = {
    name = "Zoom";
    genericName = "Zoom Web Client";
    exec = "firefox --new-window https://app.zoom.us/wc/home";
    icon = "firefox";
    categories = [ "Network" "VideoConference" ];
  };
}
