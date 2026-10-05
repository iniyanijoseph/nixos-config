{ pkgs, ... }:
let
  displayMode = pkgs.writeShellApplication {
    name = "display-mode";
    runtimeInputs = with pkgs; [
      coreutils
      hyprshade
    ];
    text = ''
      set -eu

      state_dir="''${XDG_STATE_HOME:-$HOME/.local/state}/display-mode"
      state_file="$state_dir/current"
      mkdir -p "$state_dir"

      ensure_hyprland_env() {
        if [[ -n "''${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
          return 0
        fi

        runtime="''${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
        for _attempt in $(seq 1 30); do
          for instance_dir in "$runtime"/hypr/*; do
            if [[ -S "$instance_dir/.socket.sock" ]]; then
              export HYPRLAND_INSTANCE_SIGNATURE="$(basename "$instance_dir")"
              export XDG_RUNTIME_DIR="$runtime"
              return 0
            fi
          done
          sleep 0.5
        done

        echo "display-mode: no running Hyprland instance found" >&2
        return 1
      }

      ensure_hyprland_env || exit 75

      current_mode() {
        hyprshade current 2>/dev/null || true
      }

      remember() {
        printf '%s\n' "$1" > "$state_file"
      }

      enable_mode() {
        case "$1" in
          grayscale|sepia)
            hyprshade on "$1"
            remember "$1"
            ;;
          *)
            echo "display-mode: unknown mode: $1" >&2
            exit 2
            ;;
        esac
      }

      disable_if_current() {
        local mode="$1"
        if [[ "$(current_mode)" == "$mode" ]]; then
          hyprshade off
          remember off
        fi
      }

      command="''${1:-}"
      mode="''${2:-}"

      case "$command" in
        toggle)
          if [[ "$mode" != "grayscale" && "$mode" != "sepia" ]]; then
            echo "Usage: display-mode toggle {grayscale|sepia}" >&2
            exit 2
          fi
          if [[ "$(current_mode)" == "$mode" ]]; then
            hyprshade off
            remember off
          else
            enable_mode "$mode"
          fi
          ;;

        set)
          desired="''${3:-}"
          if [[ "$mode" != "grayscale" && "$mode" != "sepia" ]]; then
            echo "Usage: display-mode set {grayscale|sepia} {true|false}" >&2
            exit 2
          fi
          case "$desired" in
            true|1|on)
              enable_mode "$mode"
              ;;
            false|0|off)
              disable_if_current "$mode"
              ;;
            *)
              echo "Usage: display-mode set {grayscale|sepia} {true|false}" >&2
              exit 2
              ;;
          esac
          ;;

        status)
          if [[ "$mode" != "grayscale" && "$mode" != "sepia" ]]; then
            echo false
            exit 0
          fi
          if [[ "$(current_mode)" == "$mode" ]]; then
            echo true
          else
            echo false
          fi
          ;;

        current)
          current_mode
          ;;

        off)
          hyprshade off
          remember off
          ;;

        restore)
          saved="off"
          if [[ -r "$state_file" ]]; then
            saved="$(cat "$state_file")"
          fi
          case "$saved" in
            grayscale|sepia)
              enable_mode "$saved"
              ;;
            *)
              hyprshade off
              remember off
              ;;
          esac
          ;;

        *)
          cat >&2 <<'EOF'
Usage:
  display-mode toggle grayscale|sepia
  display-mode set grayscale|sepia true|false
  display-mode status grayscale|sepia
  display-mode current
  display-mode off
  display-mode restore
EOF
          exit 2
          ;;
      esac
    '';
  };
in
{
  home.packages = [
    pkgs.hyprshade
    displayMode
  ];

  xdg.configFile."hypr/shaders/grayscale.glsl".text = ''
    #version 300 es
    precision highp float;

    in vec2 v_texcoord;
    uniform sampler2D tex;
    out vec4 fragColor;

    void main() {
        vec4 color = texture(tex, v_texcoord);
        float gray = dot(color.rgb, vec3(0.2126, 0.7152, 0.0722));
        fragColor = vec4(vec3(gray), color.a);
    }
  '';

  xdg.configFile."hypr/shaders/sepia.glsl".text = ''
    #version 300 es
    precision highp float;

    in vec2 v_texcoord;
    uniform sampler2D tex;
    out vec4 fragColor;

    void main() {
        vec4 color = texture(tex, v_texcoord);
        vec3 c = color.rgb;
        vec3 sepia = vec3(
            dot(c, vec3(0.393, 0.769, 0.189)),
            dot(c, vec3(0.349, 0.686, 0.168)),
            dot(c, vec3(0.272, 0.534, 0.131))
        );
        fragColor = vec4(clamp(sepia, 0.0, 1.0), color.a);
    }
  '';

  systemd.user.services.restore-display-mode = {
    Unit = {
      Description = "Restore grayscale/sepia display mode";
      After = [ "graphical-session.target" ];
    };
    Service = {
      Type = "oneshot";
      ExecStart = "${displayMode}/bin/display-mode restore";
      Restart = "on-failure";
      RestartSec = "2s";
    };
    Install.WantedBy = [ "default.target" ];
  };
}
