{pkgs, ...}:
{
  home.packages = with pkgs; [
    sleek-todo
    topydo
  ];
}
