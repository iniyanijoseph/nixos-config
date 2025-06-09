{pkgs, ...}:
{
  home.packages = with pkgs; [
    hugo

    python313

    lua

    jdt-language-server

    rustc
    cargo
    rustfmt
    rust-analyzer
    clippy

    ruby
    bundix

    postgresql

    racket

    ciao # Prolog
  ];

  programs.java.enable = true;
  
}
