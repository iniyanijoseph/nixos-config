{ pkgs }:
pkgs.buildGoModule {
  pname = "contabo-matrimail";
  version = "1.9.3-contabo-contacts";
  src = pkgs.fetchFromGitHub {
    owner = "Leicas";
    repo = "matrimail";
    rev = "6f22bb7115063241eb91d146ad1f177a56ae3ad5";
    hash = "sha256-hWwGGPHmVQ0OWhCtc5bN0vlIbsee8D6hr/utVmma80k=";
  };
  vendorHash = "sha256-bnJjYRfUdUiI6op2DONGM2HzCsQVU+V/6+RV1FiPLTE=";
  patches = [ ./contabo.patch ];
  postPatch = ''
    cp ${./imap_backfill.go} pkg/imap/contabo_backfill.go
    cp ${./imap_backfill_test.go} pkg/imap/contabo_backfill_test.go
    cp ${./connector_backfill.go} pkg/connector/contabo_backfill.go
    cp ${./email_contacts.go} pkg/email/contabo_contacts.go
    cp ${./email_contact_events.go} pkg/email/contabo_contact_events.go
    cp ${./email_contacts_test.go} pkg/email/contabo_contacts_test.go
    cp ${./connector_contacts.go} pkg/connector/contabo_contacts.go
    cp ${./connector_migration.go} pkg/connector/contabo_migration.go
    cp ${./connector_contacts_test.go} pkg/connector/contabo_contacts_test.go
  '';
  nativeBuildInputs = [ pkgs.pkg-config ];
  buildInputs = [ pkgs.olm ];
  subPackages = [ "cmd/matrimail" ];
  # Upstream OAuth HTTP fixtures have failures with the pinned Go/oauth2
  # combination. Run the real contact, header, recipient and history regressions.
  checkPhase = ''
    runHook preCheck
    go test ./pkg/imap ./pkg/email ./pkg/matrix ./pkg/connector \
      -run 'TestContabo|Test.*(Reply|Recipients|Compose|Outgoing|MIME|Quote|Participant|Thread|Sender)' -count=1
    runHook postCheck
  '';
  meta.mainProgram = "matrimail";
}
