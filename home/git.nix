{ ... }:
{
  programs.delta = {
    enable = true;
    options = {
      line-numbers = true;
      side-by-side = false;
      diff-so-fancy = true;
      navigate = true;
    };
  };

  programs.git = {
    enable = true;

    settings = {
      user.email = "iniyanijoseph@gmail.com";
      user.name = "Wug";
      init.defaultBranch = "main";
      merge.conflictstyle = "diff3";
      diff.colorMoved = "default";
      pull.ff = "only";
      color.ui = true;
    };

  };

  programs.gh = {
    enable = true;
    settings.git_protocol = "https";
    gitCredentialHelper.enable = true;
  };

  xdg.configFile."git/.gitignore".text = ''
    .vscode
  '';

  # Replace the old manually-created function that expands every `git`
  # command to `sudo git`. Keeping a thin function here lets Home Manager
  # overwrite that file deterministically while Git runs as the current user.
  xdg.configFile."fish/functions/git.fish" = {
    force = true;
    text = ''
      function git --wraps=git --description 'Run Git as the current user'
        command git $argv
      end
    '';
  };

  programs.fish.shellAliases = {
    g = "lazygit";
    gf = "onefetch --number-of-file-churns 0 --no-color-palette";
    ga = "git add";
    gaa = "git add --all";
    gs = "git status";
    gb = "git branch";
    gm = "git merge";
    gd = "git diff";
    gpl = "git pull";
    gplo = "git pull origin";
    gps = "git push";
    gpso = "git push origin";
    gpst = "git push --follow-tags";
    gcl = "git clone";
    gc = "git commit";
    gcm = "git commit -m";
    gcma = "git add --all && git commit -m";
    gtag = "git tag -ma";
    gch = "git checkout";
    gchb = "git checkout -b";
    glog = "git log --oneline --decorate --graph";
    glol = "git log --graph --pretty='%Cred%h%Creset -%C(auto)%d%Creset %s %Cgreen(%ar) %C(bold blue)<%an>%Creset'";
    glola = "git log --graph --pretty='%Cred%h%Creset -%C(auto)%d%Creset %s %Cgreen(%ar) %C(bold blue)<%an>%Creset' --all";
    glols = "git log --graph --pretty='%Cred%h%Creset -%C(auto)%d%Creset %s %Cgreen(%ar) %C(bold blue)<%an>%Creset' --stat";
  };
}
