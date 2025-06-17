{pkgs, ...}:
{
  home.packages = with pkgs; [
    hugo

    python313

    lua
    ruby
    bundix

    postgresql

    racket

    ciao # Prolog

    ffmpeg
  ];

  programs.java.enable = true;
  
}
