"""Assemble the final dataset: tags + geocodes + register fields.

Joins the classification tags onto the geocoded charity table and exports
the headline artefacts:

  data/processed/uk_overseas_charities.csv   - the full dataset, one row
                                               per charity
  data/processed/charities.geojson           - point features for the
                                               geocoded subset
  docs/charities.geojson                     - the same features for the
                                               web map (docs/ is what
                                               GitHub Pages serves)

Normal run (after the full tagging batch):
    python src/assemble.py

Preview run (a labelled sample, e.g. while the paid batch is pending):
    python src/assemble.py --tags outputs/sample_tags_preview.csv --preview

--preview marks the map data so the page shows a "preview sample" banner,
and skips writing the headline CSV (a partial dataset should never look
like the finished one).
"""

import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
GEOCODED_PATH = REPO_ROOT / "data" / "processed" / "international_geocoded.csv"
DEFAULT_TAGS = REPO_ROOT / "data" / "processed" / "sdg_tags.csv"
CSV_OUT = REPO_ROOT / "data" / "processed" / "uk_overseas_charities.csv"
GEOJSON_OUT = REPO_ROOT / "data" / "processed" / "charities.geojson"
MAP_DATA_OUT = REPO_ROOT / "docs" / "charities.geojson"


def build_dataset(geocoded: pd.DataFrame, tags: pd.DataFrame) -> pd.DataFrame:
    # Left join keeps every charity even if (unexpectedly) untagged, so the
    # final row count always equals the Day-1 population and gaps are visible.
    df = geocoded.merge(tags, on="organisation_number", how="left")
    untagged = df["primary_sdg"].isna().sum()
    if untagged:
        print(f"note: {untagged:,} charities have no tag yet")
    return df


def build_geojson(df: pd.DataFrame, preview: bool = False) -> dict:
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
                "orgno": int(row["organisation_number"]),
                "sdg": int(row["primary_sdg"]),
                "sdg_title": row["primary_sdg_title"],
                "engagement": row["overseas_engagement"],
                "summary": row["focus_summary"],
                "sdg_conf": row["sdg_confidence"],
                "eng_conf": row["engagement_confidence"],
            },
        })
    return {
        "type": "FeatureCollection",
        # "meta" is a foreign member (allowed by the GeoJSON spec); the map
        # page reads it to label the snapshot and show the preview banner.
        "meta": {
            "snapshot": str(date.today()),
            "count": len(features),
            "preview": preview,
        },
        "features": features,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tags", type=Path, default=DEFAULT_TAGS,
                        help="tags CSV to join (default: the full run)")
    parser.add_argument("--preview", action="store_true",
                        help="mark the map data as a labelled preview sample")
    args = parser.parse_args()

    if not args.tags.exists():
        raise SystemExit(f"{args.tags} not found - run the tagging stage "
                         "first (or pass --tags with a sample).")

    geocoded = pd.read_csv(GEOCODED_PATH)
    tags = pd.read_csv(args.tags)
    df = build_dataset(geocoded, tags)

    if args.preview:
        print("preview mode: skipping the headline dataset CSV")
    else:
        df.to_csv(CSV_OUT, index=False)
        print(f"Saved {len(df):,} rows to {CSV_OUT}")

    geojson = build_geojson(df, preview=args.preview)
    for path in ([GEOJSON_OUT] if args.preview else [GEOJSON_OUT, ]) + [MAP_DATA_OUT]:
        path.parent.mkdir(parents=True, exist_ok=True)
    if not args.preview:
        with open(GEOJSON_OUT, "w") as f:
            json.dump(geojson, f)
        print(f"Saved {len(geojson['features']):,} features to {GEOJSON_OUT}")
    with open(MAP_DATA_OUT, "w") as f:
        json.dump(geojson, f)
    print(f"Saved {len(geojson['features']):,} features to {MAP_DATA_OUT}"
          + (" (preview)" if args.preview else ""))


if __name__ == "__main__":
    main()
