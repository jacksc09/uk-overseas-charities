"""Assemble the final dataset: tags + geocodes + register fields.

Joins the LLM tags (sdg_tags.csv) onto the geocoded charity table and
exports the two headline artefacts:

  data/processed/uk_overseas_charities.csv   - the full dataset, one row
                                               per charity
  data/processed/charities.geojson           - point features for the
                                               geocoded subset, ready for
                                               a web map

Run from the repo root:  python src/assemble.py
"""

import json
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
GEOCODED_PATH = REPO_ROOT / "data" / "processed" / "international_geocoded.csv"
TAGS_PATH = REPO_ROOT / "data" / "processed" / "sdg_tags.csv"
CSV_OUT = REPO_ROOT / "data" / "processed" / "uk_overseas_charities.csv"
GEOJSON_OUT = REPO_ROOT / "data" / "processed" / "charities.geojson"


def build_dataset(geocoded: pd.DataFrame, tags: pd.DataFrame) -> pd.DataFrame:
    # Left join keeps every charity even if (unexpectedly) untagged, so the
    # final row count always equals the Day-1 population and gaps are visible.
    df = geocoded.merge(tags, on="organisation_number", how="left")
    untagged = df["primary_sdg"].isna().sum()
    if untagged:
        print(f"note: {untagged:,} charities have no tag yet")
    return df


def build_geojson(df: pd.DataFrame) -> dict:
    """Point features for the mappable subset (geocode ok + tagged)."""
    mappable = df[(df["geocode_status"] == "ok") & df["primary_sdg"].notna()]
    features = []
    for _, row in mappable.iterrows():
        features.append({
            "type": "Feature",
            # GeoJSON coordinate order is [longitude, latitude]
            "geometry": {
                "type": "Point",
                "coordinates": [round(row["longitude"], 5),
                                round(row["latitude"], 5)],
            },
            "properties": {
                "name": row["charity_name"],
                "regno": int(row["registered_charity_number"]),
                "sdg": int(row["primary_sdg"]),
                "sdg_title": row["primary_sdg_title"],
                "engagement": row["overseas_engagement"],
                "summary": row["focus_summary"],
            },
        })
    return {"type": "FeatureCollection", "features": features}


def main() -> None:
    geocoded = pd.read_csv(GEOCODED_PATH)
    tags = pd.read_csv(TAGS_PATH)

    df = build_dataset(geocoded, tags)
    df.to_csv(CSV_OUT, index=False)
    print(f"Saved {len(df):,} rows to {CSV_OUT}")

    geojson = build_geojson(df)
    with open(GEOJSON_OUT, "w") as f:
        json.dump(geojson, f)
    print(f"Saved {len(geojson['features']):,} point features to {GEOJSON_OUT}")


if __name__ == "__main__":
    main()
