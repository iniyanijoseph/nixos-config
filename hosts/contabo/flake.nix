{
  description = "Contabo NixOS VPS (separate stable flake in the desktop config repo)";

  # Intentionally separate from the desktop's nixos-unstable lock file.
  # Copy the working /etc/nixos/flake.lock here on first migration.
  inputs = {
    # Emergency PHP fixes for CVE-2026-109618 / CVE-2026-109619.
    # NixOS 26.05 backport merge commit (PHP 8.4.27).
    # Return to the nixos-26.05 channel only after verifying that the
    # channel contains this security patch.
    nixpkgs.url = "github:NixOS/nixpkgs/8c259fc0dd1f3ccc1aaf4f9156ab16b7328b5a4f";
    disko.url = "github:nix-community/disko";
    disko.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { nixpkgs, disko, ... }:
    let
      system = "x86_64-linux";
      emailPkgs = import nixpkgs {
        inherit system;
        # Matrimail currently requires deprecated libolm for Matrix E2EE.
        # Keep this exception limited to the opt-in development shell.
        config.permittedInsecurePackages = [ "olm-3.2.16" ];
      };
    in {
    # Compare Google Takeout JSON, embedded photo EXIF, GPS and upload mtime
    # without mutating photos, sidecars, files cache or Memories database.
    packages.x86_64-linux.contabo-photo-audit =
      let pkgs = import nixpkgs { inherit system; };
      in pkgs.writeShellScriptBin "contabo-photo-audit" ''
        export PYTHONDONTWRITEBYTECODE=1
        export PATH="${pkgs.exiftool}/bin:$PATH"
        exec ${pkgs.python3}/bin/python3 ${./photo-metadata-audit.py} "$@"
      '';

    checks.x86_64-linux.contabo-photo-audit-unit-tests =
      let pkgs = import nixpkgs { inherit system; };
      in pkgs.runCommand "contabo-photo-audit-unit-tests" { } ''
        export PYTHONDONTWRITEBYTECODE=1
        export CONTABO_PHOTO_AUDIT_SCRIPT="${./photo-metadata-audit.py}"
        ${pkgs.python3}/bin/python3 ${./test_photo_metadata_audit.py}
        touch "$out"
      '';

    # Journaled Files-mtime repair. Opt-in only: never invoked by any service,
    # NixOS switch, timer, or ordinary nix flake check.
    packages.x86_64-linux.contabo-photo-mtime-repair =
      let pkgs = import nixpkgs { inherit system; };
      in pkgs.writeShellScriptBin "contabo-photo-mtime-repair" ''
        export PYTHONDONTWRITEBYTECODE=1
        exec ${pkgs.python3}/bin/python3 ${./photo-mtime-repair.py} "$@"
      '';

    checks.x86_64-linux.contabo-photo-mtime-repair-tests =
      let pkgs = import nixpkgs { inherit system; };
      in pkgs.runCommand "contabo-photo-mtime-repair-tests" { } ''
        export PYTHONDONTWRITEBYTECODE=1
        export CONTABO_MTIME_REPAIR_SCRIPT="${./photo-mtime-repair.py}"
        ${pkgs.python3}/bin/python3 ${./test_photo_mtime_repair.py}
        touch "$out"
      '';

    # Scoped, sanitized read-only collector/archive inspector. This may
    # realize a pinned Python executable in /nix/store, but it does not
    # write to any application directory, database, Matrix room, or archive.
    packages.x86_64-linux.contabo-discord-audit =
      let pkgs = import nixpkgs { inherit system; };
      in pkgs.writeShellScriptBin "contabo-discord-audit" ''
        export PYTHONDONTWRITEBYTECODE=1
        export CONTABO_DISCORD_SCOPE_PATH="${./discord-archive/scope.py}"
        exec ${pkgs.python3}/bin/python3 ${./discord-archive/audit.py}
      '';

    # Syntax-only tests: they do not run audits, migrations or monitoring.
    # Nix flake check builds these checks using the pinned Nixpkgs inputs.
    checks.x86_64-linux.contabo-observe-fish-syntax =
      let pkgs = import nixpkgs { inherit system; };
      in pkgs.runCommand "contabo-observe-fish-syntax" { } ''
        ${pkgs.fish}/bin/fish -n ${./observe.fish}
        ${pkgs.fish}/bin/fish -n ${./stop-transient-monitoring.fish}
        ${pkgs.fish}/bin/fish -n ${./setup-phase1.fish}
        touch "$out"
      '';

    checks.x86_64-linux.contabo-migration-python-syntax =
      let pkgs = import nixpkgs { inherit system; };
      in pkgs.runCommand "contabo-migration-python-syntax" { } ''
        ${pkgs.python3}/bin/python3 -c 'import ast, pathlib
for path in [
    "${./migration-queue.py}",
    "${./matrix-commands.py}",
    "${./matrix-periodic-status.py}",
    "${./matrix-alert.py}",
    "${./discord-archive/scope.py}",
    "${./discord-archive/audit.py}",
    "${./photo-metadata-audit.py}",
    "${./photo-mtime-repair.py}",
]:
    ast.parse(pathlib.Path(path).read_text(encoding="utf-8"), filename=path)
'
        touch "$out"
      '';

    devShells.x86_64-linux.email-bridge = emailPkgs.mkShell {
      packages = [
        emailPkgs.go
        emailPkgs.git
        emailPkgs.pkg-config
        emailPkgs.olm
        emailPkgs.gcc
      ];
    };

    nixosConfigurations.contabo = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        disko.nixosModules.disko
        ./configuration.nix
      ];
    };
  };
}
