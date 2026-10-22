# Pin the current mautrix bridge releases without moving the Contabo
# NixOS/Nextcloud nixpkgs pin. Hashes are from upstream Nixpkgs package
# definitions as of 2026-10-21. All binaries use experimental pure-Go
# Olm (goolm) to avoid the deprecated libolm C library.
{ pkgs }:
let
  version = "26.10";
  tag = "v0.2610.0";
in {
  gmessages = pkgs.buildGoModule {
    pname = "mautrix-gmessages";
    inherit version;
    src = pkgs.fetchFromGitHub {
      owner = "mautrix";
      repo = "gmessages";
      inherit tag;
      hash = "sha256-14ocZjE0SgjjTzpCx9njUq7kDDHcZZnEtRJ3Mm7eFis=";
    };
    vendorHash = "sha256-9yHVzEOXkura/RVPVflfR0NfegVk28eUI6E0b6P+1qQ=";
    tags = [ "goolm" ];
    ldflags = [ "-s" "-w" "-X" "main.Tag=${tag}" ];
    doCheck = true;
    meta.mainProgram = "mautrix-gmessages";
  };

  slack = pkgs.buildGoModule {
    pname = "mautrix-slack";
    inherit version;
    src = pkgs.fetchFromGitHub {
      owner = "mautrix";
      repo = "slack";
      inherit tag;
      hash = "sha256-NYTYamZsPIvVZpqUZ5d8EMMDMsIlEBfpHbXANdDQtgs=";
    };
    vendorHash = "sha256-FtEjVcWBcgX9cFZn6oSFpW4Y7rQaHbivD30aoAhgY0o=";
    tags = [ "goolm" ];
    # Known upstream test failure, as recorded in Nixpkgs.
    checkFlags = [ "-skip=TestSlackBlocksToMatrixMessageMention" ];
    ldflags = [ "-s" "-w" "-X" "main.Tag=${tag}" ];
    doCheck = true;
    meta.mainProgram = "mautrix-slack";
  };
}
