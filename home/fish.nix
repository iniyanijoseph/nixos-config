{pkgs, ...}:
{
  home.packages = with pkgs; [
    fd
    libnotify
  ];

  programs.direnv = {
    enable = true;
    enableFishIntegration = true;
    nix-direnv.enable = true;
  };

  programs.fzf = {
    enable = true;
    enableFishIntegration = true;
    defaultCommand = "fd --type f --hidden --follow --exclude .git";
    fileWidget.command = "fd --type f --hidden --follow --exclude .git";
    changeDirWidget.command = "fd --type d --hidden --follow --exclude .git";
  };

  programs.nix-index = {
    enable = true;
    enableFishIntegration = true;
  };

  programs.zoxide = {
    enable = true;
    enableFishIntegration = true;
  };

  programs.fish = {
    enable = true;
    plugins = [
      {
        name = "done";
        src = pkgs.fishPlugins.done.src;
      }
    ];
    shellAliases = {
      cat = "bat";
      top = "btop";
      ls = "eza";
      fetch = "macchina; cpufetch";
      nixedit = "cd /etc/nixos/; hx";
      nixup = "nh os switch";
      purduevpn = "sudo openconnect --protocol=anyconnect webvpn.purdue.edu";
      typsthtml = "typst c --features html -f html";
      typstwhtml = "typst w --features html -f html";
    };
  };
}
