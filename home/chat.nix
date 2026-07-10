{ pkgs, ... }:
{
  # Ripcord is a single non-Electron Qt client that covers Discord and
  # Slack. Free for Discord; Slack works unpaid too, just nags for a
  # license.
  home.packages = with pkgs; [ dissent ];

  # zoom-us drags along a fair amount of local cache/log clutter under
  # ~/.zoom and ~/.config/zoomus.conf for what's usually occasional calls.
  # Zoom's web client covers joining/hosting fine - in your Zoom profile,
  # enable "Always use my browser when I click a join link" under
  # Settings > General to stop it from nagging you to install the app.
  xdg.desktopEntries.zoom-web = {
    name = "Zoom";
    genericName = "Zoom Web Client";
    exec = "qutebrowser --target window https://app.zoom.us/wc/home";
    terminal = false;
    icon = "qutebrowser";
    categories = [ "Network" "VideoConference" ];
  };

  xdg.desktopEntries.google-messages = {
    name = "Google Messages";
    genericName = "SMS/RCS Messaging";
    exec = "qutebrowser --target window https://messages.google.com/web";
    terminal = false;
    icon = "qutebrowser";
    categories = [ "Network" "Chat" ];
  };

  xdg.desktopEntries.whatsapp = {
    name = "WhatsApp";
    genericName = "WhatsApp Web";
    exec = "qutebrowser --target window https://web.whatsapp.com";
    terminal = false;
    icon = "qutebrowser";
    categories = [ "Network" "Chat" ];
  };
}
