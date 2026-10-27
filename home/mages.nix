{ pkgs }:
let
  # Mirror the upstream Mages Nix package at a fixed, reproducible release.
  # https://github.com/mlm-games/Mages/blob/main/nix/flake.nix
  version = "5.2.7";
  artifact = {
    x86_64-linux = {
      file = "mages-5.2.7-x86_64.AppImage";
      hash = "sha256-L/xK25aNU5k3rHQkBveyAvT4nO/2r9lelrosP9p2bLU=";
    };
    aarch64-linux = {
      file = "mages-5.2.7-aarch64.AppImage";
      hash = "sha256-+9QINXmLBClRKAKkzDTSTptv5ekokX3cFBRCkHTQ0DE=";
    };
  }.${pkgs.stdenv.hostPlatform.system};
in
pkgs.stdenvNoCC.mkDerivation {
  pname = "mages";
  inherit version;

  src = pkgs.fetchurl {
    url = "https://github.com/mlm-games/Mages/releases/download/${version}/${artifact.file}";
    hash = artifact.hash;
  };

  dontFixup = true;
  nativeBuildInputs = [ pkgs.makeWrapper ];

  unpackPhase = ''
    runHook preUnpack
    cp "$src" ./source
    chmod +x ./source
    ./source --appimage-extract
    runHook postUnpack
  '';

  sourceRoot = "squashfs-root";

  installPhase = ''
    runHook preInstall

    mkdir -p "$out/libexec/mages"
    cp -r . "$out/libexec/mages/"
    makeWrapper "$out/libexec/mages/AppRun" "$out/bin/mages"

    install -Dm644 io.github.mlm_games.mages.desktop \
      "$out/share/applications/io.github.mlm_games.mages.desktop"
    substituteInPlace "$out/share/applications/io.github.mlm_games.mages.desktop" \
      --replace-fail 'Exec=Mages %U' 'Exec=mages %U' \
      --replace-fail 'Icon=mages' 'Icon=io.github.mlm_games.mages'

    install -Dm644 lib/Mages.png \
      "$out/share/icons/hicolor/512x512/apps/io.github.mlm_games.mages.png"
    install -Dm644 usr/share/metainfo/io.github.mlm_games.mages.metainfo.xml \
      "$out/share/metainfo/io.github.mlm_games.mages.metainfo.xml"

    runHook postInstall
  '';

  meta = with pkgs.lib; {
    description = "Experimental multiplatform Matrix client";
    homepage = "https://github.com/mlm-games/Mages";
    license = licenses.agpl3Only;
    mainProgram = "mages";
    platforms = [ "x86_64-linux" "aarch64-linux" ];
  };
}
