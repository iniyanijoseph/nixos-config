{ pkgs }:
let
  state = "/var/lib/migration-queue/finish-setup";
  worker = pkgs.writeShellScriptBin "contabo-finish-setup" ''
    set -euo pipefail
    echo executed >> ${state}/executions
    while [[ -e ${state}/hold-worker ]]; do
      sleep 0.2
    done
    if [[ -e ${state}/fail-worker ]]; then
      exit 23
    fi
    if [[ -s ${state}/switch-target ]]; then
      target=$(cat ${state}/switch-target)
      rm ${state}/switch-target
      # Exercise the real NixOS activation program from inside the service.
      "$target/bin/switch-to-configuration" switch
      echo switched > ${state}/switch-complete
    fi
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
    specialisation.activation.configuration = {
      # Covers the first switch that installs the declarative resume unit too.
      imports = [ ./finish-setup.nix ];
      environment.etc."contabo-activation-probe".text = "switched";
      systemd.tmpfiles.rules = [ "f /run/contabo-switched 0600 root root -" ];
    };
  };
in pkgs.testers.runNixOSTest {
  name = "contabo-setup-runtime-switch-and-boot-resume";
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

    runtime.shutdown()
    runtime.start()
    runtime.wait_for_unit("multi-user.target")
    runtime.succeed("test $(wc -l < ${state}/executions) -eq 1")
    runtime.succeed("test ! -e /run/systemd/system/contabo-finish-setup.service")

    declared.shutdown()
    declared.start()
    declared.wait_for_unit("multi-user.target")
    declared.wait_until_succeeds("test $(wc -l < ${state}/executions) -eq 2")

    for node in [runtime, declared]:
        before = int(node.succeed("wc -l < ${state}/executions").strip())
        target = node.succeed("readlink -f /run/current-system").strip() + "/specialisation/activation"
        node.succeed(f"echo {target} > ${state}/switch-target")
        node.succeed("touch ${state}/hold-worker")
        # Run the real launcher in the background so we can inspect its worker
        # while active, then verify that its viewer waits for process exit.
        node.succeed("(bash ${./finish-setup.sh} > ${state}/viewer.log 2>&1; echo $? > ${state}/viewer-exit) </dev/null >/dev/null 2>&1 &")
        node.wait_until_succeeds("systemctl is-active --quiet contabo-finish-setup.service", timeout=30)
        assert node.succeed("systemctl show contabo-finish-setup.service -p Type --value").strip() == "exec"
        assert node.succeed("systemctl show contabo-finish-setup.service -p Job --value").strip() in ("", "0")
        node.succeed("sleep 1; test ! -e ${state}/viewer-exit")
        node.succeed("rm ${state}/hold-worker")
        # A oneshot worker deadlocks the switch when it starts active targets;
        # this must complete without stopping/killing the worker from outside.
        node.wait_until_succeeds("test -f ${state}/switch-complete", timeout=120)
        node.wait_until_succeeds("test -f ${state}/viewer-exit", timeout=30)
        node.succeed("test $(cat ${state}/viewer-exit) -eq 0")
        node.succeed("test $(cat /etc/contabo-activation-probe) = switched")
        node.succeed("test -e /run/contabo-switched")
        node.succeed(f"test $(wc -l < ${state}/executions) -eq {before + 1}")

        # Type=exec marks startup complete, not commissioning success. The
        # launcher must still return failure when the worker later exits 23.
        node.succeed("touch ${state}/fail-worker")
        node.fail("bash ${./finish-setup.sh}", timeout=30)
        assert node.succeed("systemctl show contabo-finish-setup.service -p ExecMainStatus --value").strip() == "23"
  '';
}
