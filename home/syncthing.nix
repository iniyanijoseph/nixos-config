{pkgs, ...}:
{
  home.packages = with pkgs; [
    
  ];

  services.syncthing {
    enable = true;
    datadir="home/wug";
    openDefaultPorts=true;
    user="wug";
    group="users";
    guiAddress="0.0.0.0:8384";
  };
}
