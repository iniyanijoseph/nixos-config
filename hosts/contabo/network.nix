{ ... }:
{
  # Contabo supplies a static address; DHCP was not used by its Debian image.
  # Match by MAC since Debian called the adapter eth0 and NixOS called it ens18.
  networking.useDHCP = false;
  networking.nameservers = [ "195.179.224.53" "209.126.15.53" ];

  systemd.network.enable = true;
  systemd.network.networks."10-uplink" = {
    matchConfig.MACAddress = "00:50:56:68:a5:43";
    networkConfig.DHCP = "no";
    address = [
      "213.199.55.255/20"
      "2a02:c207:2368:5354::1/64"
    ];
    routes = [
      { Gateway = "213.199.48.1"; GatewayOnLink = true; }
      { Gateway = "fe80::1"; GatewayOnLink = true; }
    ];
    dns = [ "195.179.224.53" "209.126.15.53" ];
    linkConfig.RequiredForOnline = "routable";
  };
}
