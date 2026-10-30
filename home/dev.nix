{pkgs, ...}:
{
  home.packages = with pkgs; [
    hugo

    python313
    nodejs

    lua
    ruby
    bundix

    postgresql

    racket-minimal

    swi-prolog

    ffmpeg

    gnumake

    temurin-bin
  ];

}
