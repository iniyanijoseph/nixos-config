{ pkgs, ... }:

{
  home.packages = with pkgs; [geary];
}
