{ pkgs, ... }:
{
  home.packages = with pkgs; [eza];
  programs.bat = {
    enable = true;
    config = {
      pager = "less -FR";
      theme = "gruvbox-dark";
    };
    extraPackages = with pkgs.bat-extras; [
      batman
      batpipe
      batgrep
      batdiff
    ];
  };
}
