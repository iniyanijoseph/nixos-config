{ pkgs }:
let
  files = pkgs.runCommand "contabo-discord-login-source" {} ''
    mkdir -p "$out"
    cp ${./discord-login.cjs} "$out/discord-login.cjs"
    cp ${./discord-login-policy.cjs} "$out/discord-login-policy.cjs"
    cp ${./discord-login-preload.cjs} "$out/discord-login-preload.cjs"
    cp ${./discord-login-renderer.cjs} "$out/discord-login-renderer.cjs"
    cp ${./discord-login.html} "$out/discord-login.html"
  '';
in pkgs.writeShellApplication {
  name = "contabo-discord-login";
  runtimeInputs = [ pkgs.electron pkgs.coreutils ];
  text = ''
    if [[ $(uname -n) == contabo || -z "''${DISPLAY:-}''${WAYLAND_DISPLAY:-}" ]]; then
      echo 'Run this on your graphical Linux laptop.' >&2
      exit 2
    fi
    exec electron ${files}/discord-login.cjs "$@"
  '';
}
