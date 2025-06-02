{pkgs, ...}:
{
  home.packages = with pkgs; [
    hugo
    python313
    lua
  ];

  programs.java.enable = true;
  
}
