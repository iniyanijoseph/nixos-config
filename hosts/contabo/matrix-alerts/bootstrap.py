#!/usr/bin/env python3
"""One-time Matrix alert bot bootstrap. Run as root ON Contabo.

Requires a Synapse *server admin* Matrix access token, prompted securely.
Creates non-admin account, private room and bot token file. No NixOS switch.
"""
import getpass
import json
import os
from pathlib import Path
import secrets
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

HOST = "http://127.0.0.1:8008"
SERVER_NAME = "iniyanjoseph.com"
USER = "@server-alerts:" + SERVER_NAME
OWNER = "@me:" + SERVER_NAME
DEST = Path("/var/lib/secrets/matrix-alerts.json")


def api(method, path, data=None, token=None):
    body = None if data is None else json.dumps(data).encode("utf-8")
    url = HOST + path
    req = Request(url, data=body, method=method,
                  headers={"Content-Type": "application/json",
                           **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urlopen(req, timeout=20) as resp:
            return json.load(resp)
    except HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Matrix HTTP {err.code} ({path}): {detail[:400]}") from None


def main():
    if os.geteuid() != 0:
        raise RuntimeError("Run as root on Contabo")
    if DEST.exists():
        print(f"Already provisioned at {DEST}; leaving existing credentials unchanged.")
        return
    print("Requires a Synapse SERVER-ADMIN access token; it will not be saved.")
    admin_token = getpass.getpass("Admin Matrix access token: ").strip()
    if not admin_token:
        raise RuntimeError("Empty admin token")
    # Verify permissions before making any changes.
    admin_check = api("GET", "/_synapse/admin/v1/users/" + quote(OWNER, safe="") +
                      "/admin", token=admin_token)
    if not admin_check.get("admin"):
        raise RuntimeError("Provided account is not a Synapse server administrator")
    password = secrets.token_urlsafe(40)
    # Synapse Admin API. Account creation does NOT change public registration.
    api("PUT", "/_synapse/admin/v2/users/" + quote(USER, safe=""),
        {"password": password, "admin": False, "displayname": "Contabo Alerts",
         "deactivated": False}, token=admin_token)
    auth = api("POST", "/_matrix/client/v3/login",
               {"type": "m.login.password",
                "identifier": {"type": "m.id.user", "user": USER},
                "password": password, "initial_device_display_name": "Contabo notifications"})
    bot_token = auth["access_token"]
    room = api("POST", "/_matrix/client/v3/createRoom",
               {"name": "Server Alerts", "topic": "Contabo services and migration notifications",
                "visibility": "private", "preset": "private_chat",
                "invite": [OWNER],
                "creation_content": {"m.federate": False}},
               token=bot_token)
    DEST.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = DEST.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as output:
        json.dump({"homeserver": "https://matrix.iniyanjoseph.com",
                   "room_id": room["room_id"], "access_token": bot_token}, output)
        output.write("\n")
    os.chmod(tmp, 0o600)
    tmp.replace(DEST)
    print(f"Provisioned bot {USER}.")
    print("Created private, unfederated Server Alerts room:", room["room_id"])
    print(f"Invited {OWNER}: accept invitation in Cinny/Element.")
    print("Credentials saved root-only:", DEST)
    print("Test: sudo python3 /etc/nixos/hosts/contabo/matrix-alert.py 'Contabo test' ")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, URLError, KeyError) as err:
        print("Bootstrap stopped:", err, file=sys.stderr)
        sys.exit(1)
