#!/usr/bin/env python3
"""Send plain-text private Matrix alerts; no external Python dependencies.

Root-readable JSON config outside Git:
  {"homeserver": "https://matrix.iniyanjoseph.com",
   "room_id": "!internal-room-id:iniyanjoseph.com",
   "access_token": "private-token"}

Prefer a dedicated non-admin bot account joined to a private room.
Do not send sensitive raw logs, credentials, or Discord message contents.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

CONFIG = Path("/var/lib/secrets/matrix-alerts.json")


def send(text, config_path=CONFIG):
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    server = cfg["homeserver"].rstrip("/")
    room = cfg["room_id"]
    token = cfg["access_token"]
    if not server.startswith("https://") or not room.startswith("!") or not token:
        raise ValueError("Expected HTTPS homeserver, internal !room_id and nonempty access token")
    txid = f"contabo-{time.time_ns()}-{os.getpid()}"
    endpoint = (f"{server}/_matrix/client/v3/rooms/"
                f"{quote(room, safe='')}/send/m.room.message/{txid}")
    payload = json.dumps({"msgtype": "m.text", "body": text},
                         ensure_ascii=False).encode("utf-8")
    request = Request(endpoint, data=payload, method="PUT",
                      headers={"Content-Type": "application/json",
                               "Authorization": "Bearer " + token})
    with urlopen(request, timeout=15) as response:
        if response.status not in (200, 201):
            raise RuntimeError(f"Matrix send returned HTTP {response.status}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("message", help="plain-text notification")
    parser.add_argument("--config", default=str(CONFIG))
    args = parser.parse_args()
    try:
        send(args.message, args.config)
    except (OSError, ValueError, KeyError, HTTPError, URLError) as error:
        print(f"Matrix alert delivery failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
