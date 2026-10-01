{ pkgs, ... }:
let
  # Waybar 0.15.0 has a Hyprland rendering regression where the layer is
  # created but the bar itself is invisible. Keep the rest of nixpkgs current
  # and pin only Waybar to the last working release until that regression is
  # fixed upstream.
  waybar014 = (pkgs.waybar.override {
    # The 0.15 nixpkgs expression vendors a newer cava subproject than 0.14
    # expects. We do not use the cava module, so disabling it keeps this
    # source-only downgrade small and avoids the mismatched vendored source.
    cavaSupport = false;
  }).overrideAttrs (old: rec {
    version = "0.14.0";
    src = pkgs.fetchFromGitHub {
      owner = "Alexays";
      repo = "Waybar";
      tag = version;
      hash = "sha256-mGiBZjfvtZZkSHrha4UF2l1Ogbij8J//r2h4gcZAJ6w=";
    };

    # Hyprland's Lua config provider no longer accepts Waybar's legacy
    # "dispatch workspace N" IPC string. Patch numeric workspace clicks to
    # use the Lua dispatcher form that this Hyprland configuration expects.
    postPatch = (old.postPatch or "") + ''
      substituteInPlace src/modules/hyprland/workspace.cpp \
        --replace-fail \
          'm_ipc.getSocket1Reply("dispatch workspace " + std::to_string(id()));' \
          'm_ipc.getSocket1Reply("/dispatch hl.dsp.focus({ workspace = \"" + std::to_string(id()) + "\" })");'
    '';
  });
in
{
  programs.waybar = {
    enable = true;
    package = waybar014;
    systemd.enable = false;
  };
}
