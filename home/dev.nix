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

    ciao # Prolog

    ffmpeg
  ];

  programs.java.enable = true;
  
}
