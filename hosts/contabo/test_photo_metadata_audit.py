#!/usr/bin/env python3
"""Unit tests for the Takeout comparison rules; no real photos or network."""
import importlib.util
from pathlib import Path
import tempfile
import os
import unittest
import json

SOURCE = Path(os.environ.get("CONTABO_PHOTO_AUDIT_SCRIPT", str(Path(__file__).resolve().parent / "photo-metadata-audit.py")) )
spec = importlib.util.spec_from_file_location("photo_audit", SOURCE)
photo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(photo)

class PhotoAuditTests(unittest.TestCase):
    def test_exact_sidecar(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "IMG_1000.jpg"
            a = Path(folder) / "IMG_1000.jpg.supplemental-metadata.json"
            b = Path(folder) / "IMG_1000.jpg.json"
            self.assertEqual(photo.resolve_sidecars(p, [a]), [a])
            self.assertEqual(photo.resolve_sidecars(p, [a, b]), sorted([a,b]))
            self.assertEqual(photo.resolve_sidecars(p, [Path(folder)/"IMG_2000.jpg.json"]), [])

    def test_read_google_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "IMG_1000.jpg.json"
            p.write_text(json.dumps({
                "creationTime":{"timestamp":"1700000000"},
                "photoTakenTime":{"timestamp":"1500000000"},
                "geoDataExif":{"latitude":37.2,"longitude":-122.1}}))
            epoch, loc, err = photo.epoch_of(p)
            self.assertEqual(epoch, 1500000000)
            self.assertEqual(loc, (37.2,-122.1))
            self.assertIsNone(err)
            p.write_text("{}")
            self.assertEqual(photo.epoch_of(p)[2], "no_valid_timestamp")

    def test_exif_dates(self):
        epoch = 1500000000
        utc = __import__("datetime").datetime.fromtimestamp(
            epoch, __import__("datetime").timezone.utc
        ).strftime("%Y:%m:%d %H:%M:%S")
        self.assertEqual(photo.compare_date(epoch, {"DateTimeOriginal": utc}),
                         "embedded_date_matches_utc")
        self.assertEqual(photo.compare_date(epoch, {}), "missing_embedded_date")
        self.assertEqual(photo.compare_date(epoch, {"DateTimeOriginal": "1990:01:01 01:02:03"}),
                         "embedded_date_conflicts_with_takeout")

    def test_gps_signs(self):
        self.assertEqual(photo.coordinates({
            "GPSLatitude":37.2,"GPSLongitude":122.1,
            "GPSLatitudeRef":"N","GPSLongitudeRef":"W"}), (37.2, -122.1))
        self.assertIsNone(photo.coordinates({}))

if __name__ == "__main__":
    unittest.main()
