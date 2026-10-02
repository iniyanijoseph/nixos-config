{ pkgs, ... }:
let
  websitePullOnBoot = pkgs.writeShellApplication {
    name = "website-pull-on-boot";
    runtimeInputs = with pkgs; [
      coreutils
      git
      libnotify
    ];
    text = ''
      set -u

      repo="$HOME/Desktop/iniyanijoseph.github.io"

      notify_user() {
        local urgency="$1"
        local title="$2"
        local body="$3"
        local attempt

        # The service may start slightly before SwayNC. Retry notifications
        # briefly so a conflict message is not lost during session startup.
        for ((attempt = 0; attempt < 15; attempt++)); do
          if notify-send -a "Website Git" -u "$urgency" "$title" "$body"; then
            return 0
          fi
          sleep 2
        done
        return 0
      }

      if [[ ! -d "$repo/.git" ]]; then
        notify_user critical           "Website repository missing"           "Could not find $repo, so the startup pull was skipped."
        exit 0
      fi

      cd "$repo"

      # Never interfere with a merge/rebase/cherry-pick that was already in
      # progress when the machine shut down.
      git_dir="$(git rev-parse --git-dir)"
      if [[ -f "$git_dir/MERGE_HEAD" || -d "$git_dir/rebase-merge" ||
            -d "$git_dir/rebase-apply" || -f "$git_dir/CHERRY_PICK_HEAD" ]]; then
        notify_user critical           "Website Git operation needs attention"           "A Git operation is already in progress in $repo. Startup pull was skipped."
        exit 0
      fi

      branch="$(git branch --show-current)"
      if [[ -z "$branch" ]]; then
        notify_user critical           "Website repository is detached"           "The website repository is on a detached HEAD, so startup pull was skipped."
        exit 0
      fi

      if upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"; then
        remote="''${upstream%%/*}"
      else
        remote="origin"
        upstream="$remote/$branch"
      fi

      # A network failure is the one case worth retrying automatically; the
      # user service uses Restart=on-failure below.
      if ! git fetch --prune --quiet "$remote"; then
        echo "website-pull-on-boot: fetch from $remote failed; will retry" >&2
        exit 75
      fi

      if ! git rev-parse --verify --quiet "$upstream^{commit}" >/dev/null; then
        notify_user critical           "Website upstream branch missing"           "Could not resolve $upstream after fetching $remote. Startup pull was skipped."
        exit 0
      fi

      head="$(git rev-parse HEAD)"
      upstream_head="$(git rev-parse "$upstream^{commit}")"

      # Already synchronized, or locally ahead of the fetched upstream.
      if [[ "$head" == "$upstream_head" ]] ||
         git merge-base --is-ancestor "$upstream_head" "$head"; then
        exit 0
      fi

      # Test the exact fetched commit in Git's object database first. This does
      # not modify the index or working tree. Only perform the real merge if
      # Git proves that the committed histories merge without conflicts.
      if ! merge_check="$(git merge-tree --write-tree "$head" "$upstream_head" 2>&1)"; then
        printf '%s\n' "$merge_check" >&2
        notify_user critical           "Website pull has merge conflicts"           "Remote changes conflict with local commits in $repo. Nothing was merged."
        exit 0
      fi

      # This is the merge half of git pull, using the exact commit just checked
      # above. It also allows a clean divergence even though interactive Git is
      # configured globally with pull.ff=only.
      if ! git merge --no-edit "$upstream_head"; then
        # merge-tree already proved the committed histories are compatible, so
        # this normally means local uncommitted files would be overwritten.
        if git rev-parse --verify --quiet MERGE_HEAD >/dev/null; then
          git merge --abort || true
        fi
        notify_user critical           "Website pull blocked by local changes"           "Remote history is conflict-free, but local working-tree changes prevented the pull. No merge was left in progress."
        exit 0
      fi
    '';
  };
in
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

  systemd.user.services.website-git-pull = {
    Unit = {
      Description = "Pull website repository after login";
    };
    Service = {
      Type = "oneshot";
      ExecStart = "${websitePullOnBoot}/bin/website-pull-on-boot";
      # If networking is not ready yet, retry until the fetch succeeds.
      Restart = "on-failure";
      RestartSec = "30s";
    };
    Install.WantedBy = [ "default.target" ];
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
