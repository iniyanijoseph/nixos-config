{pkgs, ...}:
{
  home.packages = with pkgs; [
    hugo

    python313

    lua
    ruby
    bundix

    postgresql

    racket-minimal

    swi-prolog

    ffmpeg
  ];

  programs.java.enable = true;
  
}
