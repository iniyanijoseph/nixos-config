{ pkgs }:
let
  application = pkgs.runCommand "mautrix-manager-0.2.1" {
    src = pkgs.fetchurl {
      url = "https://github.com/mautrix/manager/releases/download/v0.2.1/mautrix-manager-linux-x64-0.2.1.zip";
      sha256 = "8a55dc5022c5d52d13c58e05c72ad2d0bfff3fa9dac19d96e5eb84608f282479";
    };
    nativeBuildInputs = [ pkgs.unzip pkgs.makeWrapper ];
  } ''
    mkdir -p "$out/libexec" "$out/bin"
    unzip -q "$src" -d "$out/libexec"
    mapfile -t executables < <(find "$out/libexec" -type f -name mautrix-manager)
    test "''${#executables[@]}" = 1
    chmod +x "''${executables[0]}"
    makeWrapper ${pkgs.lib.getExe pkgs.steam-run-free} "$out/bin/mautrix-manager" \
      --add-flags "''${executables[0]}" \
      --add-flags --disable-setuid-sandbox
  '';
in pkgs.writeShellApplication {
  name = "contabo-bridge-manager";
  runtimeInputs = [ pkgs.openssh pkgs.curl pkgs.coreutils pkgs.gnugrep application ];
  text = builtins.readFile ./bridge-manager.sh;
}
