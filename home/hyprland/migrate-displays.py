#!/usr/bin/env python3
"""Convert nwg-displays' legacy generated files to Hyprland Lua once."""

from __future__ import annotations

import json
from pathlib import Path
import sys


def quoted(value: str) -> str:
    return json.dumps(value)


def migrate_monitors(source: Path, destination: Path) -> None:
    blocks = ["-- Migrated from nwg-displays monitors.conf by Home Manager."]
    monitor_blocks: dict[str, list[str]] = {}
    order: list[str] = []

    for original in source.read_text().splitlines():
        line = original.strip()
        if not line.startswith("monitor="):
            continue
        fields = [field.strip() for field in line.removeprefix("monitor=").split(",")]
        if len(fields) < 2:
            continue
        output = fields[0]
        if output not in monitor_blocks:
            monitor_blocks[output] = [f"    output = {quoted(output)}"]
            order.append(output)
        props = monitor_blocks[output]

        if fields[1] == "disable":
            props.append("    disabled = true")
        elif fields[1] == "transform" and len(fields) >= 3:
            props.append(f"    transform = {int(fields[2])}")
        elif len(fields) >= 4:
            props.extend([
                f"    mode = {quoted(fields[1])}",
                f"    position = {quoted(fields[2])}",
                f"    scale = {float(fields[3]):g}",
            ])
            index = 4
            while index + 1 < len(fields):
                key, value = fields[index], fields[index + 1]
                if key == "mirror":
                    props.append(f"    mirror = {quoted(value)}")
                elif key == "bitdepth":
                    props.append(f"    bitdepth = {int(value)}")
                elif key == "vrr":
                    props.append(f"    vrr = {int(value)}")
                index += 2

    for output in order:
        props = ",\n".join(monitor_blocks[output])
        blocks.append(f"hl.monitor({{\n{props}\n}})")
    if len(blocks) > 1:
        destination.write_text("\n\n".join(blocks) + "\n")


def migrate_workspaces(source: Path, destination: Path) -> None:
    blocks = ["-- Migrated from nwg-displays workspaces.conf by Home Manager."]
    for original in source.read_text().splitlines():
        line = original.strip()
        if not line.startswith("workspace="):
            continue
        fields = [field.strip() for field in line.removeprefix("workspace=").split(",")]
        if not fields:
            continue
        props = [f"    workspace = {quoted(fields[0])}"]
        for field in fields[1:]:
            if field.startswith("monitor:"):
                props.append(f"    monitor = {quoted(field.removeprefix('monitor:'))}")
            elif field == "default:true":
                props.append("    default = true")
        blocks.append("hl.workspace_rule({\n" + ",\n".join(props) + "\n})")
    if len(blocks) > 1:
        destination.write_text("\n\n".join(blocks) + "\n")


def migrate(directory: Path, stem: str, converter) -> None:
    source = directory / f"{stem}.conf"
    destination = directory / f"{stem}.lua"
    if source.is_file() and not destination.exists():
        converter(source, destination)


config_dir = Path(sys.argv[1])
config_dir.mkdir(parents=True, exist_ok=True)
migrate(config_dir, "monitors", migrate_monitors)
migrate(config_dir, "workspaces", migrate_workspaces)
