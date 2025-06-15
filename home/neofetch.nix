{ pkgs, ... }:
{
  home.packages = with pkgs; [ macchina cpufetch ];
}
