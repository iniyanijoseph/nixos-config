{ pkgs }:
pkgs.testers.runNixOSTest {
  name = "contabo-single-use-invitations";
  nodes.machine = { ... }: {
    imports = [ ./server-admin.nix ];
    services.matrix-synapse = {
      enable = true;
      settings = {
        server_name = "iniyanjoseph.com";
        public_baseurl = "http://127.0.0.1:8008/";
        registration_shared_secret = "vm-fixture-only";
        report_stats = false;
        database = { name = "sqlite3"; args.database = "/var/lib/matrix-synapse/homeserver.db"; };
        listeners = [{ port = 8008; bind_addresses = [ "127.0.0.1" ]; type = "http";
          resources = [{ names = [ "client" ]; compress = false; }]; }];
      };
    };
    services.nginx.enable = true;
    environment.systemPackages = [ (pkgs.python3.withPackages (ps: [ps.pyyaml])) pkgs.curl ];
    virtualisation.memorySize = 2048;
  };
  testScript = ''
    machine.start()
    machine.wait_for_unit("matrix-synapse.service")
    machine.wait_for_open_port(8008)
    machine.succeed("python3 ${./test_invite_live.py} ${./server-admin.py}")
    machine.wait_for_unit("nginx.service")
    machine.succeed("curl -fsS -H 'Host: matrix.iniyanjoseph.com' http://127.0.0.1/invite/ | grep 'Create your account'")
    machine.succeed("test $(curl -s -o /dev/null -w '%{http_code}' -H 'Host: matrix.iniyanjoseph.com' http://127.0.0.1/_synapse/admin/v1/registration_tokens) != 200")
  '';
}
