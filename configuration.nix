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

  # This was previously unset, which meant hardware.cpu.amd.updateMicrocode
  # (set via mkDefault in hardware-configuration.nix and nixos-hardware) had
  # nothing to default to and effectively never applied. AMD microcode updates
  # carry real power-management and P-state fixes, not just security patches.
  hardware.enableRedistributableFirmware = true;

  # ---- Power management ----
  # nixos-hardware's thinkpad/laptop modules already default services.tlp.enable
  # to true as long as power-profiles-daemon is disabled, but we set both
  # explicitly here so this doesn't silently change if those defaults ever do.
  services.power-profiles-daemon.enable = false;
  services.tlp = {
    enable = true;
    settings = {
      CPU_SCALING_GOVERNOR_ON_AC = "performance";
      CPU_SCALING_GOVERNOR_ON_BAT = "powersave";
      CPU_ENERGY_PERF_POLICY_ON_AC = "performance";
      CPU_ENERGY_PERF_POLICY_ON_BAT = "power";

      # You're fine with a louder fan, so let AC power draw run hot for
      # sustained boost -- thinkfan below keeps it thermally safe.
      PLATFORM_PROFILE_ON_AC = "performance";
      PLATFORM_PROFILE_ON_BAT = "low-power";

      # Battery longevity: stop charging at 80%, resume at 75%.
      # Bump STOP_CHARGE_THRESH_BAT0 toward 90-95 if you're usually on
      # battery rather than plugged in most of the day.
      START_CHARGE_THRESH_BAT0 = 75;
      STOP_CHARGE_THRESH_BAT0 = 90;

      RUNTIME_PM_ON_BAT = "auto";
      USB_AUTOSUSPEND = 1;
      WIFI_PWR_ON_BAT = "on";
      SOUND_POWER_SAVE_ON_BAT = 1;
    };
  };

  # Fan control: you said louder fan is fine, so ramp up a bit earlier than
  # thinkfan's stock curve to keep the CPU cooler and sustaining boost
  # clocks longer under load. The last entry hands control back to the
  # firmware's own auto behavior above 80C as a safety net -- this doesn't
  # override thermal protection, it just makes the fan more proactive below it.
  services.thinkfan = {
    enable = true;
    levels = [
      [ 0 0 50 ]
      [ 1 45 55 ]
      [ 2 48 58 ]
      [ 3 50 61 ]
      [ 4 53 64 ]
      [ 5 56 68 ]
      [ 6 60 72 ]
      [ 7 65 80 ]
      [ "level auto" 80 32767 ]
    ];
  };

  # Battery-state notifications/monitoring (low battery warnings, etc.)
  services.upower.enable = true;

  # Firmware/EC updates -- sometimes ship power-management fixes.
  services.fwupd.enable = true;

  # Compressed RAM swap. There's no swap device configured at all right now,
  # so under memory pressure the system has nothing to fall back on but the
  # OOM killer. This costs a bit of idle RAM/CPU but saves you from that.
  zramSwap = {
    enable = true;
    memoryPercent = 50;
  };

  # Your firmware only exposes s2idle (confirmed via `cat /sys/power/mem_sleep`
  # -- no [deep] option listed), so there's no S3 to opt into. Instead, this
  # nudges the NVMe drive into deeper autonomous power states during idle/
  # standby, which is one of the few real levers left for reducing s2idle
  # power draw on hardware stuck without S3.
  boot.kernelParams = [ "nvme_core.default_ps_max_latency_us=5500" ];

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
    file

    # Kitty
    kitty

    pavucontrol
    pamixer
    brightnessctl

    direnv

    helix

    # Copy Paste
    wl-clipboard

    # Steam
    mangohud
    protonup-ng

    # VPN
    networkmanager-openconnect
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
        command = "hyprland";
        user = "wug";
      };
      default_session = {
        command = "${tuigreet} --greeting 'Hello!' --asterisks --remember --remember-user-session --time --cmd hyprland";
        user = "greeter";
      };
    };    
  };

  # Steam
  programs.steam.enable = true;
  programs.steam.gamescopeSession.enable = true;
  programs.gamemode.enable = true;

  # Desktop
  programs.hyprland = {
    enable = true;
    xwayland.enable = true;
  };

  environment.sessionVariables = {
    NIXOS_OZONE_WL = "1";
    EDITOR = "hx";
    STEAM_EXTRA_COMPAT_TOOLS_PATHS = "\${HOME}/.steam/root/compatibilitytools.d";
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
    # Was true -- only needed if other devices on your network need to
    # discover this machine (e.g. network printer/file sharing). Flip back
    # to true if you rely on that.
    openFirewall = false;
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

  # Unlock GNOME Keyring on login via greetd (needed for Geary/GOA to
  # store and retrieve credentials).
  security.pam.services.greetd.enableGnomeKeyring = true;

  # Firewall.
  networking.firewall.enable = true;
  # networking.firewall.allowedTCPPorts = [ ... ];
  # networking.firewall.allowedUDPPorts = [ ... ];

  # System Version - Don't Edit
  system.stateVersion = "25.05"; 
}
