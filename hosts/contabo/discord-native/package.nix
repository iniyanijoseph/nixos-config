{ pkgs }:
let
  legacy = import pkgs.path {
    system = pkgs.stdenv.hostPlatform.system;
    config.permittedInsecurePackages = [ "olm-3.2.16" ];
  };
in legacy.mautrix-discord.overrideAttrs (old: {
  doCheck = true;
  checkFlags = [ "-run=TestContaboArchive" ];
  patches = (old.patches or []) ++ [ ./replay.patch ];
  postPatch = (old.postPatch or "") + ''
    cp ${./archive_replay.go} archive_replay.go
    cp ${./archive_replay_test.go} archive_replay_test.go
  '';
})
