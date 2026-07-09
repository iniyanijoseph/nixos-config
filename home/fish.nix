{pkgs, ...}:
{
  programs.fish = {
    enable = true;
    shellAliases = {
      cat = "bat";
      top = "btop";
      ls = "eza";
      fetch = "macchina; cpufetch";
      # NOTE: this makes every `git` invocation run as root. Convenient for
      # a single-user laptop where the store/worktree is root-owned, but it
      # also means every commit and file `git` touches is written as root,
      # and it silently swallows your normal-user git config in edge cases.
      # Worth revisiting - see the redundancies note.
      git = "sudo git";
      nixedit = "cd /etc/nixos/; sudo hx";
      purduevpn = "sudo openconnect --protocol=anyconnect webvpn.purdue.edu";
      typsthtml = "typst c --features html -f html";
      typstwhtml = "sudo typst w --features html -f html";
    };
  };
}
