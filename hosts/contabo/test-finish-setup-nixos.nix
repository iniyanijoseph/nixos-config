{ pkgs }:
let
  state = "/var/lib/migration-queue/finish-setup";
  worker = pkgs.writeShellScriptBin "contabo-finish-setup" ''
    echo executed >> ${state}/executions
    echo 'Fixture worker completed' > ${state}/summary.txt
  '';
  # Substitute only the external build, not any launcher/systemd code.
  nixFixture = pkgs.hiPrio (pkgs.writeShellScriptBin "nix" ''
    test "$1" = build
    ${pkgs.coreutils}/bin/ln -sfn ${worker} ${state}/runner
  '');
  common = {
    networking.hostName = "contabo";
    environment.systemPackages = [ pkgs.git pkgs.bash pkgs.util-linux nixFixture ];
    virtualisation.memorySize = 1024;
  };
in pkgs.testers.runNixOSTest {
  name = "contabo-setup-runtime-and-boot-resume";
  nodes = {
    runtime = { ... }: { imports = [ common ]; };
    declared = { ... }: { imports = [ common ./finish-setup.nix ]; };
  };
  testScript = ''
    start_all()
    for node in [runtime, declared]:
        node.wait_for_unit("multi-user.target")
        # Exercise the actual NixOS read-only unit directory that broke the
        # first release, rather than a writable Ubuntu /etc fixture.
        node.fail("touch /etc/systemd/system/contabo-write-probe.service")
        node.succeed("mkdir -p /etc/nixos; git -C /etc/nixos init -b main")
        node.succeed("git -C /etc/nixos -c user.name=test -c user.email=test@example.com commit --allow-empty -m fixture")
        node.succeed("bash ${./finish-setup.sh}")
        node.wait_until_succeeds("test -f ${state}/executions")
        node.succeed("test -f /run/systemd/system/contabo-finish-setup.service")
        node.succeed("test -f ${state}/resume-on-boot")
        node.succeed("test $(wc -l < ${state}/executions) -eq 1")

    runtime.succeed("bash ${./finish-setup.sh} --status")
    runtime.fail("systemctl is-enabled --quiet contabo-finish-setup.service")
    declared.succeed("systemctl is-enabled --quiet contabo-finish-setup.service")

    runtime.reboot()
    runtime.wait_for_unit("multi-user.target")
    runtime.succeed("test $(wc -l < ${state}/executions) -eq 1")
    runtime.succeed("test ! -e /run/systemd/system/contabo-finish-setup.service")

    declared.reboot()
    declared.wait_for_unit("multi-user.target")
    declared.wait_until_succeeds("test $(wc -l < ${state}/executions) -eq 2")
  '';
}
