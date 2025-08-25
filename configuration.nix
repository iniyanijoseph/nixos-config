{config, pkgs, ... }:
{
  # Bootloader.
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;
  
  networking.hostName = "nixos"; # Define your hostname.

  # Enable networking
  networking.networkmanager.enable = true;

  # Set your time zone.
  time.timeZone = "America/Chicago";

  # Select internationalisation properties.
  i18n.defaultLocale = "en_US.UTF-8";

  i18n.extraLocaleSettings = {
    LC_ADDRESS = "en_US.UTF-8";
    LC_IDENTIFICATION = "en_US.UTF-8";
    LC_MEASUREMENT = "en_US.UTF-8";
    LC_MONETARY = "en_US.UTF-8";
    LC_NAME = "en_US.UTF-8";
    LC_NUMERIC = "en_US.UTF-8";
    LC_PAPER = "en_US.UTF-8";
    LC_TELEPHONE = "en_US.UTF-8";
    LC_TIME = "en_US.UTF-8";
  };


  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  # Define a user account.
  users.users.wug = {
    isNormalUser = true;
    description = "wug";
    extraGroups = [ "networkmanager" "wheel" ];
    packages = with pkgs; [];
  };

  # Fish
  programs.fish.enable = true;
  users.defaultUserShell = pkgs.fish;

  # Allow unfree packages
  nixpkgs.config.allowUnfree = true;

  # List packages installed in system profile. To search, run:
  environment.systemPackages = with pkgs; [
    networkmanagerapplet
    sqlite
    
    # Package and Repo Managing
    wget
    git
    gh

    # Zip
    zip
    unzip

    # Kitty
    kitty

    # Power Management
    power-profiles-daemon

    pavucontrol

    wayland
    glib
    direnv

    helix
  ];

  

  # Bluetooth
  hardware.bluetooth.enable = true;
  hardware.bluetooth.powerOnBoot = true;
  services.blueman.enable = true;

  # Display Manager
  services.greetd =
  let
    tuigreet = "${pkgs.tuigreet}/bin/tuigreet";
  in
  {
    enable = true;
    settings = {
      initial_session = {
        command = "Hyprland";
        user = "wug";
      };
      default_session = {
        command = "${tuigreet} --greeting 'Hello!' --asterisks --remember --remember-user-session --time --cmd Hyprland";
        user = "greeter";
      };
    };    
  };

  # Desktop
  programs.hyprland = {
    enable = true;
    xwayland.enable = true;
  };

  environment.sessionVariables = {
    NIXOS_OZONE_WL = "1";
    EDITOR = "hx";
  };

  hardware = {
    graphics.enable = true;
  };

  # Enable sound and screen sharing
  services.pulseaudio.enable = false;
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    alsa.support32Bit = true;
    pulse.enable = true;
  };

  hardware.alsa.enablePersistence=true;
  
  services.devmon.enable = true;
  services.gvfs.enable = true;
  services.udisks2.enable = true;

  # Configure keymap in X11
  services.xserver = {
    xkb = {
      layout = "us";
      variant = "";
    };
  };

  services.libinput = {
    touchpad = {
      disableWhileTyping = true;
    };
  };

  services.kanata = {
    enable = true;
    keyboards.canary.configFile = ./kanata.cfg;
  };

  # Printing
  services.printing.enable = true;
  services.avahi = {
    enable = true;
    nssmdns4 = true;
    openFirewall = true;
  };

  programs.nix-ld = {
    enable = true; 
  };
 
  # Some programs need SUID wrappers, can be configured further or are
  # started in user sessions.
  # programs.mtr.enable = true;
  # programs.gnupg.agent = {
  #   enable = true;
  #   enableSSHSupport = true;
  # };

  # Enable the OpenSSH daemon.
  services.openssh.enable = true;

  # Firewall.
  networking.firewall.enable = true;
  # networking.firewall.allowedTCPPorts = [ ... ];
  # networking.firewall.allowedUDPPorts = [ ... ];

  # System Version - Don't Edit
  system.stateVersion = "25.05"; 
}
