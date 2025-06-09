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
  ];

  programs.java.enable = true;
  
}
