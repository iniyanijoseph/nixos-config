# Google Messages (SMS/RCS) and Slack Matrix bridges — STAGED ONLY

These bridges are defined in `../bridges-extra.nix` using fixed
mautrix v26.10 source/dependency hashes in `../bridges-extra-pkgs.nix`.
They are disabled:

```nix
contabo.messagingBridges.sms.enable = false;
contabo.messagingBridges.slack.enable = false;
```

**Do not enable while Discord history collection is running.**
Nothing in this directory logs into accounts, synchronizes history,
creates Matrix rooms, or starts new services without your explicit
activation and initial device/workspace authentication.

## Architecture

| Source | Matrix bridge | Local HTTP port | Auth | Historical limitation |
|---|---|---:|---|---|
| Android Google Messages SMS + RCS | mautrix-gmessages v26.10 | 127.0.0.1:29320 | Google-account pairing; phone approval | Only phone-accessible history; initial Matrix backfill cannot be expanded into existing rooms |
| Four Slack workspaces | mautrix-slack v26.10 | 127.0.0.1:29321 | Workspace-specific personal login (`xoxc` + `xoxd`) or supported manager | History restricted by API permissions, membership, retention and Matrix limitations |

The updated Slack code can recover from some upstream changes, but
**there is no guarantee personal Slack authentication will stay valid**.
Managed Beeper integrations are maintained centrally and can change
faster; a self-hosted bridge does not automatically inherit every
Beeper-side credential workaround. Slack workspace policies may prevent
personal bridges. Reauthenticate per workspace if tokens expire.

Google Messages **QR login is discontinued**. For current pairing see
https://docs.mau.fi/bridges/go/gmessages/authentication.html .
The paired Android phone needs network access; this is not a cloud SMS
archive independent of the phone.

## Important history limitations

- Ordinary Synapse supports sending historical messages in **new,
  empty Matrix rooms**, using their old event timestamps. It does
  **not** support inserting arbitrary older events before messages
  already in an existing room.
- Enable a supported initial backfill setting *before* connecting
  accounts and creating portal rooms.
- `backfill.queue`'s backward-import feature requires the Beeper
  homeserver, not ordinary Synapse. It is **not** available here.
- For SMS/RCS, the phone controls what old messages are exposed. A
  large numeric Matrix limit does not cause Google to supply missing
  history.
- For Slack, even a fully authorized account cannot retrieve
  deleted messages or messages removed by retention policies.
  Thread replies and private channel histories require permissions.
- Consider separately exporting Slack workspace data **if an
  administrator permits it** and SMS backups for archive completeness.
  Neither export automatically imports as native Matrix rooms.

## Two-phase activation (ONLY after the pending Discord job)

**Phase 1:** After Discord finishes and the queued Photos work
completes, rebuild/switch the NixOS configuration *with both enable
flags still false*. This creates the two dedicated system users and
private data directories. Synapse is **not** told to load an
appservice registration until the individual bridge is enabled.

**Phase 2:** Generate configuration and a private registration for
each appservice while it is still disabled. The official CLI is
`-e` for a template and `-g` for registration, with
`-c` and `-r` for file paths.

Build the pinned packages by Nix, *without* switching:

```fish
cd /etc/nixos

for name in gmessages slack
    BRIDGE_PACKAGE=$name nix build --impure --no-link --print-out-paths --expr '
      let
        f = builtins.getFlake (toString ./hosts/contabo);
        pkgs = import f.inputs.nixpkgs { system = "x86_64-linux"; };
        packages = import ./hosts/contabo/bridges-extra-pkgs.nix { inherit pkgs; };
      in builtins.getAttr (builtins.getEnv "BRIDGE_PACKAGE") packages
    '
end
```

Each result is a `/nix/store/...` path; use the appropriate
`bin/mautrix-gmessages` or `bin/mautrix-slack` binary from the build.
It is necessary to **test this build** on the pinned NixOS/Go toolchain;
the hashes are from published Nixpkgs package definitions but have not
yet been built on your Contabo machine.

As the bridge's dedicated service user, generate the config:

```fish
# Example: substitute the actual /nix/store result (do not guess its path).
sudo -u mautrix-gmessages /nix/store/RESULT/bin/mautrix-gmessages \
    -e -c /var/lib/mautrix-gmessages/config.yaml
```

Configure these values in the YAML **before** generating registration:
- homeserver.address `http://127.0.0.1:8008`
- homeserver.domain `iniyanjoseph.com`
- appservice.hostname `127.0.0.1`
- appservice.address `http://127.0.0.1:29320` (SMS) or `:29321` (Slack)
- appservice.port = 29320 (SMS) or 29321 (Slack)
- appservice.bot.username names that do not conflict with WhatsApp:
  `gmessagesbot`, `slackbot`
- appservice.db: dedicated SQLite under the bridge's data directory
  (check the generated v26.10 config schema)
- Matrix permissions for `@me:iniyanjoseph.com` only
- backfill.enabled = true, max_initial_messages chosen for realistic
  API limits *before account login*; start conservatively and verify
  complete imports before proceeding to a second workspace.

Then:

```fish
sudo -u mautrix-gmessages /nix/store/RESULT/bin/mautrix-gmessages \
    -g -c /var/lib/mautrix-gmessages/config.yaml \
       -r /var/lib/mautrix-gmessages/registration.yaml
```

The Slack procedure is analogous with `mautrix-slack` paths and
port 29321. Keep generated config/registration group-readable by
each bridge's group, not world-readable. Synapse will be added to that
group by the NixOS module upon activation.

Only after both the service config and registration exist, flip the
corresponding `.enable = true`, run a NixOS **build first**, inspect
evaluation, then switch. This restarts Synapse to register the new
appservice. Avoid accidentally reusing the same appservice IDs or
tokens. Install the binary specified by the NixOS package build rather
than the manual file path; the manual build is used to prepare config.

**First-run authentication** remains interactive with the Matrix bot:
- Google Messages: use `login google` and phone approval, not QR.
- Slack: pair each workspace separately. Use the documented mautrix
  manager where practical, rather than copying secrets into Matrix
  history. Don't paste `xoxc`/`xoxd` into this chat or Git.

See https://docs.mau.fi/bridges/go/setup.html and
https://docs.mau.fi/bridges/go/slack/authentication.html .

## No automatic switch

The deferred migration queue *only evaluates* the future NixOS
configurations and records readiness. DNS, mail, SMS phone pairing and
Slack logins all require separate checks. It never automatically starts
these bridges.
