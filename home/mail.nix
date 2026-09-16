{ pkgs, ... }:
{
  home.packages = (
    with pkgs;
    [
      thunderbird
      element-desktop
    ]
  );
}
