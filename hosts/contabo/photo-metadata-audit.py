#!/usr/bin/env python3
"""Read-only Google Takeout/EXIF vs filesystem audit for Nextcloud Memories.

Never writes to image, sidecar, Nextcloud database, checkpoints or the EXIF
metadata. Emits only aggregated counts, not filenames, coordinates or dates
associated with individual pictures. Does not invoke OCC or reindex.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

DEFAULT_ROOT = Path("/var/lib/nextcloud/data/wug/files/Photos/Google Photos")
MEDIA = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff",
         ".gif", ".bmp", ".mp4", ".mov", ".m4v", ".avi", ".3gp", ".mts", ".mkv"}
SUFFIXES = (".supplemental-metadata.json", ".supplemental-metadata(1).json", ".json")
DATE_KEYS = ("DateTimeOriginal", "CreateDate", "MediaCreateDate", "TrackCreateDate", "CreationDate")

def emit(label, value):
    print(f"{label}: {value}", flush=True)

def resolve_sidecars(media, sidecars):
    """Conservative filename-based match: conflicting candidates are ambiguous."""
    prefix = media.name
    exact = {p for p in sidecars if p.name in
             {prefix + ".json", prefix + ".supplemental-metadata.json",
              prefix + ".supplemental-metadata(1).json"}}
    return sorted(exact)

def epoch_of(sidecar):
    try:
        with sidecar.open("r", encoding="utf-8") as src:
            data = json.load(src)
        ts = data.get("photoTakenTime")
        epoch = int(ts.get("timestamp")) if isinstance(ts, dict) else None
        if epoch is None or not (631152000 <= epoch <= 4102444800):
            return None, None, "no_valid_timestamp"
        location = data.get("geoDataExif") or data.get("geoData") or {}
        coords = None
        if isinstance(location, dict):
            lat, lon = location.get("latitude"), location.get("longitude")
            if isinstance(lat, (float, int)) and isinstance(lon, (float, int)):
                if -90 <= lat <= 90 and -180 <= lon <= 180 and (lat != 0 or lon != 0):
                    coords = (float(lat), float(lon))
        return epoch, coords, None
    except (OSError, ValueError, TypeError, AttributeError, OverflowError):
        return None, None, "invalid_sidecar"

def parse_exif_time(value):
    if not isinstance(value, str) or not value:
        return None
    value = value.strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    return None

def compare_date(epoch, exif):
    """A naive EXIF clock may be local time; allow timezone displacement."""
    dates = [parse_exif_time(exif.get(k)) for k in DATE_KEYS]
    dates = [x for x in dates if x is not None]
    if not dates:
        return "missing_embedded_date"
    best = min(abs(x - epoch) for x in dates)
    if best <= 600:
        return "embedded_date_matches_utc"
    if best <= 14 * 3600:
        return "embedded_date_possible_timezone_offset"
    return "embedded_date_conflicts_with_takeout"

def coordinates(exif):
    lat, lon = exif.get("GPSLatitude"), exif.get("GPSLongitude")
    try:
        lat, lon = float(lat), float(lon)
        ref_lat, ref_lon = exif.get("GPSLatitudeRef"), exif.get("GPSLongitudeRef")
        if isinstance(ref_lat, str) and ref_lat.upper() in ("S", "SOUTH") and lat > 0:
            lat = -lat
        if isinstance(ref_lon, str) and ref_lon.upper() in ("W", "WEST") and lon > 0:
            lon = -lon
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    except (ValueError, TypeError):
        pass
    return None

def exif_batch(files, binary):
    """One ExifTool process per chunk, no file metadata printed."""
    args = [binary, "-json", "-n",
            "-DateTimeOriginal", "-CreateDate", "-MediaCreateDate",
            "-TrackCreateDate", "-CreationDate", "-GPSLatitude",
            "-GPSLongitude", "-GPSLatitudeRef", "-GPSLongitudeRef",
            *[str(x) for x in files]]
    try:
        out = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=180, check=False, text=True)
        if out.returncode != 0:
            return None
        results = json.loads(out.stdout)
        return results if isinstance(results, list) and len(results) == len(files) else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                    help="Nextcloud user Google Photos directory")
    ap.add_argument("--sample", type=int, default=400,
                    help="deterministic EXIF sample size; 0 scans all media")
    args = ap.parse_args()
    root = args.root.resolve()
    if args.sample < 0 or args.sample > 100000:
        ap.error("sample must be 0..100000")
    if root.is_symlink() or not root.is_dir():
        emit("BLOCK", "Canonical photo directory missing or symlink")
        return 2

    exiftool = shutil.which("exiftool") or "/run/current-system/sw/bin/exiftool"
    if not os.path.isfile(exiftool) or not os.access(exiftool, os.X_OK):
        emit("BLOCK", "ExifTool unavailable")
        return 2

    media, sidecar_by_dir, counts = [], defaultdict(list), Counter()
    emit("Mode", "read-only, sanitized and deterministic; no data changes")
    for folder, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = [d for d in directories if not (Path(folder) / d).is_symlink()]
        for filename in filenames:
            file = Path(folder) / filename
            if file.is_symlink() or not file.is_file():
                counts["skipped_special_files"] += 1
                continue
            if filename.lower().endswith(".json"):
                counts["json_files"] += 1
                sidecar_by_dir[Path(folder)].append(file)
            elif file.suffix.lower() in MEDIA:
                media.append(file)
            else:
                counts["other_files"] += 1

    counts["media_files"] = len(media)
    media.sort(key=lambda p: hashlib.sha256(str(p.relative_to(root)).encode()).hexdigest())
    selected = media if args.sample == 0 else media[:args.sample]
    counts["sampled_media"] = len(selected)
    items = []
    for file in selected:
        matches = resolve_sidecars(file, sidecar_by_dir[file.parent])
        if len(matches) == 0:
            counts["media_without_exact_sidecar"] += 1
            items.append((file, None, None))
        elif len(matches) > 1:
            counts["media_with_ambiguous_sidecars"] += 1
            items.append((file, None, None))
        else:
            timestamp, loc, error = epoch_of(matches[0])
            if error:
                counts[error] += 1
            else:
                counts["sidecars_with_capture_time"] += 1
                if loc is not None:
                    counts["sidecars_with_gps"] += 1
            items.append((file, timestamp, loc))
    for start in range(0, len(items), 50):
        batch = items[start:start + 50]
        reports = exif_batch([row[0] for row in batch], exiftool)
        if reports is None:
            counts["exif_batch_errors"] += 1
            continue
        for (file, ts, expected_gps), obj in zip(batch, reports):
            if not isinstance(obj, dict):
                counts["exif_decode_errors"] += 1
                continue
            counts["exif_inspected"] += 1
            if ts is not None:
                date_state = compare_date(ts, obj)
                counts[date_state] += 1
                if abs(file.stat().st_mtime - ts) <= 86400:
                    counts["file_mtime_within_1_day_of_takeout"] += 1
                else:
                    counts["file_mtime_differs_from_takeout"] += 1
                if expected_gps is not None:
                    actual_gps = coordinates(obj)
                    if actual_gps is None:
                        counts["takeout_gps_missing_from_exif"] += 1
                    elif max(abs(actual_gps[0] - expected_gps[0]),
                             abs(actual_gps[1] - expected_gps[1])) <= 0.002:
                        counts["takeout_gps_matches_exif"] += 1
                    else:
                        counts["takeout_gps_conflicts_with_exif"] += 1
            else:
                if any(parse_exif_time(obj.get(k)) is not None for k in DATE_KEYS):
                    counts["no_takeout_sidecar_but_exif_date_present"] += 1
                else:
                    counts["no_takeout_sidecar_and_exif_date_missing"] += 1

    emit("Root", "canonical Nextcloud Google Photos directory (path withheld)")
    emit("Media files found", counts["media_files"])
    emit("JSON files found", counts["json_files"])
    emit("Other files found", counts["other_files"])
    emit("Sample", counts["sampled_media"])
    emit("Exif inspected", counts["exif_inspected"])
    for key in (
        "media_without_exact_sidecar", "media_with_ambiguous_sidecars",
        "invalid_sidecar", "no_valid_timestamp", "sidecars_with_capture_time",
        "sidecars_with_gps", "embedded_date_matches_utc",
        "embedded_date_possible_timezone_offset",
        "embedded_date_conflicts_with_takeout", "missing_embedded_date",
        "file_mtime_within_1_day_of_takeout", "file_mtime_differs_from_takeout",
        "takeout_gps_matches_exif", "takeout_gps_missing_from_exif",
        "takeout_gps_conflicts_with_exif", "no_takeout_sidecar_but_exif_date_present",
        "no_takeout_sidecar_and_exif_date_missing",
        "exif_batch_errors", "exif_decode_errors", "skipped_special_files",
    ):
        emit(key, counts[key])
    emit("Takeout JSON name matching", "exact-only: ambiguous/truncated names intentionally not guessed")
    emit("Nextcloud Files dates", "often filesystem mtime; this audit does not change it")
    emit("Memories dates/GPS", "indexed database not audited here; reindex only after source correction")
    emit("Write actions", "NONE")
    return 0 if counts["exif_inspected"] else 2

if __name__ == "__main__":
    sys.exit(main())
