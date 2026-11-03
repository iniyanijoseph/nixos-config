{ pkgs }:
pkgs.writeShellApplication {
  name = "contabo-admin";
  runtimeInputs = [ pkgs.coreutils pkgs.systemd pkgs.nix pkgs.util-linux pkgs.postgresql_17 ];
  text = ''
    export PYTHONDONTWRITEBYTECODE=1
    export PYTHONTZPATH="${pkgs.tzdata}/share/zoneinfo"
    export CONTABO_STATS_TEMPLATE="${./server-stats.html}"
    export CONTABO_COMMISSION_SCRIPT="${./commission-integrations.py}"
    exec ${pkgs.python3.withPackages (ps: [ ps.pyyaml ])}/bin/python3 ${./server-admin.py} "$@"
  '';
}
