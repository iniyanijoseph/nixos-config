{ inputs, pkgs, ... }:
{
  programs.firefox.enable = true;
  # Pin to current behavior explicitly (silences the 26.05 default-change
  # warning - avoids needing to migrate ~/.mozilla/firefox to the XDG path).
  programs.firefox.configPath = ".mozilla/firefox";
  home.packages = with pkgs; [ openconnect qutebrowser ];
}
