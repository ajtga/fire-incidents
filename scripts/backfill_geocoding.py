"""One-off script to backfill latitude/longitude for existing fire incidents.

Usage:
    python scripts/backfill_geocoding.py

This reads `data/cbmal_fire_incidents.csv`, geocodes every row that is
missing coordinates, and writes the updated CSV back in place.

It is safe to re-run: rows that already have coordinates are skipped.
Expect ~1.5 seconds per row due to Nominatim rate limits (~2.5 min for 92 rows).
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

# Allow importing from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cbmal_fire_incidents_scraper import (
    FIELDNAMES,
    OUTPUT_FILE,
    geocode_address,
    normalize_text,
)


def main() -> None:
    if not OUTPUT_FILE.exists():
        print(f"ERROR: Dataset not found at {OUTPUT_FILE}")
        sys.exit(1)

    # Read existing rows
    rows: list[dict[str, str]] = []
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with OUTPUT_FILE.open("r", encoding=encoding, newline="") as f:
                rows = list(csv.DictReader(f))
            break
        except UnicodeDecodeError:
            continue

    if not rows:
        print("No rows found in the dataset.")
        return

    total = len(rows)
    need_geocoding = [
        row for row in rows
        if not row.get("latitude") and not row.get("longitude")
    ]

    print(f"Total rows: {total}")
    print(f"Rows needing geocoding: {len(need_geocoding)}")
    print(f"Rows already geocoded: {total - len(need_geocoding)}")
    print()

    if not need_geocoding:
        print("All rows already have coordinates. Nothing to do.")
        return

    succeeded = 0
    failed = 0

    for i, row in enumerate(need_geocoding, 1):
        local = row.get("local", "")
        cidade = row.get("cidade", "")

        print(f"[{i}/{len(need_geocoding)}] {local}")
        lat, lon = geocode_address(local, cidade)

        row["latitude"] = str(lat) if lat is not None else ""
        row["longitude"] = str(lon) if lon is not None else ""

        if lat is not None:
            succeeded += 1
        else:
            failed += 1

    # Write back
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            # Ensure all fieldnames are present (handles rows read before
            # latitude/longitude columns existed)
            clean = {field: row.get(field, "") for field in FIELDNAMES}
            writer.writerow(clean)

    print()
    print(f"Done. Geocoded {succeeded + failed} rows.")
    print(f"  Succeeded: {succeeded}")
    print(f"  Failed:    {failed}")
    print(f"Dataset saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
