"""Geocode charity head-office postcodes with postcodes.io.

postcodes.io is a free, open API built on ONS/OS open data. Its bulk
endpoint accepts up to 100 postcodes per POST, so ~19,000 charities means
only ~170 HTTP requests once postcodes are deduplicated (many charities
share a postcode, e.g. office buildings hosting several).

Interpretation caveat that must travel with this data: the postcode is the
charity's REGISTERED CONTACT ADDRESS - often a trustee's home for small
charities - not where the charity actually works.

Output: data/processed/international_geocoded.csv - international.csv plus
latitude / longitude / admin_district and a geocode_status column
("ok", "missing_postcode", or "unmatched" - unmatched usually means a
terminated or mistyped postcode). Nothing is dropped.

Run from the repo root:  python src/geocode.py
"""

from pathlib import Path

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

REPO_ROOT = Path(__file__).resolve().parent.parent
IN_PATH = REPO_ROOT / "data" / "processed" / "international.csv"
OUT_PATH = REPO_ROOT / "data" / "processed" / "international_geocoded.csv"

BULK_URL = "https://api.postcodes.io/postcodes"
BATCH_SIZE = 100  # the API's documented maximum per bulk request


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=30))
def lookup_batch(postcodes: list[str]) -> list[dict]:
    """Bulk-lookup one batch; returns the API's per-postcode result list."""
    response = requests.post(BULK_URL, json={"postcodes": postcodes}, timeout=60)
    response.raise_for_status()
    return response.json()["result"]


def main() -> None:
    df = pd.read_csv(IN_PATH)

    # Normalise before deduplicating so "ox4 1aa " and "OX4 1AA" collapse
    # into one lookup. postcodes.io itself is case/space tolerant.
    df["postcode_norm"] = df["charity_contact_postcode"].str.strip().str.upper()
    unique_postcodes = sorted(df["postcode_norm"].dropna().unique())
    print(f"{len(df):,} charities -> {len(unique_postcodes):,} unique postcodes")

    rows = []
    for start in range(0, len(unique_postcodes), BATCH_SIZE):
        batch = unique_postcodes[start : start + BATCH_SIZE]
        for item in lookup_batch(batch):
            result = item["result"]  # None when the postcode isn't found
            rows.append({
                "postcode_norm": item["query"],
                "latitude": result["latitude"] if result else None,
                "longitude": result["longitude"] if result else None,
                "admin_district": result["admin_district"] if result else None,
            })
        done = min(start + BATCH_SIZE, len(unique_postcodes))
        if done % 2000 < BATCH_SIZE or done == len(unique_postcodes):
            print(f"  looked up {done:,} / {len(unique_postcodes):,}")

    lookup = pd.DataFrame(rows)
    df = df.merge(lookup, on="postcode_norm", how="left")

    # Three-way status so downstream steps (and readers) can see exactly
    # what geocoding could and could not do.
    df["geocode_status"] = "ok"
    df.loc[df["latitude"].isna(), "geocode_status"] = "unmatched"
    df.loc[df["postcode_norm"].isna(), "geocode_status"] = "missing_postcode"

    df = df.drop(columns=["postcode_norm"])
    df.to_csv(OUT_PATH, index=False)

    print(f"\nSaved {len(df):,} rows to {OUT_PATH}")
    print("\ngeocode_status counts:")
    counts = df["geocode_status"].value_counts()
    for status, n in counts.items():
        print(f"  {status:<18} {n:>7,}  ({n / len(df):.1%})")


if __name__ == "__main__":
    main()
