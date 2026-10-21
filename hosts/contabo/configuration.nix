{ pkgs, ... }:
{
  imports = [
    ./disk-config.nix
    ./network.nix
    ./nextcloud.nix
    ./backups.nix
    ./shell.nix
  ];

  networking.hostName = "contabo";
  time.timeZone = "UTC";

  # The VPS was confirmed to boot in legacy BIOS mode (not UEFI).
  boot.loader.grub = {
    enable = true;
    device = "/dev/sda";
    efiSupport = false;
  };
  boot.initrd.availableKernelModules = [
    "ahci" "virtio_pci" "virtio_scsi" "virtio_blk" "sd_mod"
  ];

  services.openssh = {
    enable = true;
    settings = {
      PermitRootLogin = "prohibit-password"; # Keep SSH-key recovery until wug is verified.
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
    };
  };

  users.users.root.openssh.authorizedKeys.keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAgZt38lUbrdVMYWLKG9t4rT8jifg+1acs5Y4ioE8j2L contabo"
  ];
  users.users.wug = {
    isNormalUser = true;
    description = "Server administrator";
    extraGroups = [ "wheel" ];
    shell = pkgs.fish;
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAgZt38lUbrdVMYWLKG9t4rT8jifg+1acs5Y4ioE8j2L contabo"
    ];
  };

  networking.firewall.enable = true;
  networking.firewall.allowedTCPPorts = [ 22 ];

  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  # Original installation state version; do not change merely when upgrading nixpkgs.
  system.stateVersion = "26.05";
}
