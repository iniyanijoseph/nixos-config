{ pkgs, ... }:
{
  imports = [
    ./disk-config.nix
    ./network.nix
    ./nextcloud.nix
    ./backups.nix
    ./matrix.nix
    ./whatsapp.nix
    ./discord.nix
    ./email.nix
    ./mail.nix
    ./bridges-extra.nix
    ./monitoring.nix
    ./google-suite.nix
    ./finish-setup.nix
    ./integrations.nix
    ./shell.nix
  ];

  # Enabled only after provisioning root-only Restic keys and R2 credentials.
  contabo.backups.enable = true;
  # Kept off until Matrimail is built, configured and Gmail integration tested.
  contabo.emailBridge.enable = false;
  # Stage only: no mail ports, listeners, credentials or DNS changed yet.
  contabo.mail.enable = false;
  contabo.messagingBridges.sms.enable = false;
  contabo.messagingBridges.slack.enable = false;
  # Opt-in only, until transient Matrix listener/timer are stopped deliberately.
  contabo.matrixMonitoring.enable = false;
  # Enable only after checking existing Calendar/Contacts/Tasks app IDs to avoid
  # collisions with statefully installed copies; Memories stays stateful.
  contabo.googleSuite.enable = false;

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
