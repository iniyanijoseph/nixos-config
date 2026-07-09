{ pkgs, ... }:

{
  home.packages = with pkgs; [
    geary
    gcr
  ];

  services.gnome-keyring.enable = true;

  xdg.portal.enable = true;

  xdg.desktopEntries.outlook = {
    name = "Outlook";
    genericName = "Purdue Email";
    exec = "firefox --new-window https://outlook.office365.com";
    terminal = false;
    icon = "firefox";
    categories = [ "Network" "Email" ];
  };
}
