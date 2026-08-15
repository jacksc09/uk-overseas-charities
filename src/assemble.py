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
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
GEOCODED_PATH = REPO_ROOT / "data" / "processed" / "international_geocoded.csv"
INTL_PATH = REPO_ROOT / "data" / "processed" / "international.csv"
DEFAULT_TAGS = REPO_ROOT / "data" / "processed" / "sdg_tags.csv"
CSV_OUT = REPO_ROOT / "data" / "processed" / "uk_overseas_charities.csv"
GEOJSON_OUT = REPO_ROOT / "data" / "processed" / "charities.geojson"
MAP_DATA_OUT = REPO_ROOT / "docs" / "charities.geojson"
# Written by fetch_iati.py: which charities publish to the IATI aid-
# transparency registry (keyed by registered_charity_number).
IATI_PATH = REPO_ROOT / "data" / "processed" / "iati_publishers.csv"

# Contact columns carried verbatim in international.csv; cleaned versions
# (website/email/phone) are added to the final dataset here.
CONTACT_COLS = ["charity_contact_web", "charity_contact_email",
                "charity_contact_phone"]

# Register values in charity_contact_web that mean "we have no website".
# Compared case-insensitively after stripping whitespace.
WEB_SENTINELS = {
    "none", "n/a", "n.a", "n.a.", "na", "no", "no.website", "nowebsite",
    "no website", "not applicable", "tbc", "-",
}


def clean_website(raw):
    """Turn the register's messy website field into a usable URL (or None).

    Raw values include bare domains ("oxfam.org.uk"), typos
    ("htpp://...", leading "www," or "."), semicolon-joined URL pairs,
    placeholder text ("no.website", "under construction"), and even email
    addresses or postal addresses typed into the wrong box. The order
    matters: salvage what is repairable, then reject anything that could
    not be a working link.
    """
    if pd.isna(raw):
        return None
    url = str(raw).strip()
    # A semicolon usually joins two URLs ("a.org;b.org") - keep the first.
    url = url.split(";")[0].strip()
    # Leading dots are typos (".charity.org") or dressed-up sentinels
    # (".none" - which the sentinel check below then catches).
    url = url.lstrip(".")
    if not url or url.lower() in WEB_SENTINELS:
        return None
    # Free text like "under construction" contains spaces; real URLs never do.
    if " " in url:
        return None
    # Repair mangled schemes ("htpp://", "http//", "https//:", ...) by
    # stripping the broken prefix entirely - unless it is already correct.
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = re.sub(r"^h+t+p+s?[:;.,/\\]+", "", url, flags=re.IGNORECASE)
        if url.lower().startswith("www/"):
            url = "www." + url[4:]
    # Fix the common leading "www,charity.org" comma typo, then strip
    # trailing punctuation.
    if url.lower().startswith("www,"):
        url = "www." + url[4:]
    url = url.rstrip(".,")
    # Reject what cannot be a working link: no dot means no domain; an @
    # means an email address was typed into the website box; a comma means
    # a postal address or a comma-for-dot typo (commas are illegal in
    # hostnames); quotes/angle brackets are unsafe inside an href="...".
    if "." not in url or any(c in url for c in '@,"<>'):
        return None
    # https is the safe default: http-only sites usually redirect, and the
    # browser falls back if not.
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    # Drop stray dots between scheme and host ("https://.charity.org").
    url = re.sub(r"^(https?://)\.+", r"\1", url, flags=re.IGNORECASE)
    return url


def clean_email(raw):
    """Validate and lowercase the register's email field (or None).

    Trailing dots/commas are typos worth repairing ("x@gmail.com." is
    clearly "x@gmail.com"); after that, one @ with a dotted, comma-free
    domain is enough to reject the junk without being strict.
    """
    if pd.isna(raw):
        return None
    email = str(raw).strip().rstrip(".,")
    if not re.match(r"^[^@\s,]+@[^@\s,]+\.[^@\s,]+$", email):
        return None
    return email.lower()


def clean_phone(raw):
    """Keep the phone number as given, unless it is an obvious placeholder.

    The register contains junk like "--", "00", "+44" and "12345". Rule:
    at least six digits, not all the same digit. Six (not seven) so real
    short helpline numbers survive - the data includes Samaritans' 116123.
    """
    if pd.isna(raw):
        return None
    phone = str(raw).strip()
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 6 or len(set(digits)) == 1:
        return None
    return phone


def build_dataset(geocoded: pd.DataFrame, tags: pd.DataFrame) -> pd.DataFrame:
    # Left join keeps every charity even if (unexpectedly) untagged, so the
    # final row count always equals the Day-1 population and gaps are visible.
    df = geocoded.merge(tags, on="organisation_number", how="left")
    untagged = df["primary_sdg"].isna().sum()
    if untagged:
        print(f"note: {untagged:,} charities have no tag yet")
    return df


def build_geojson(df: pd.DataFrame, preview: bool = False,
                  snapshot: str | None = None) -> dict:
    """Point features for the mappable subset (geocode ok + tagged)."""
    mappable = df[(df["geocode_status"] == "ok") & df["primary_sdg"].notna()]
    features = []
    for _, row in mappable.iterrows():
        props = {
            "name": row["charity_name"],
            "regno": int(row["registered_charity_number"]),
            "orgno": int(row["organisation_number"]),
            "sdg": int(row["primary_sdg"]),
            "sdg_title": row["primary_sdg_title"],
            "engagement": row["overseas_engagement"],
            "summary": row["focus_summary"],
            "sdg_conf": row["sdg_confidence"],
            "eng_conf": row["engagement_confidence"],
        }
        # Contact keys are omitted when missing (about a third of charities
        # have no website) so the file does not carry thousands of nulls.
        if pd.notna(row["website"]):
            props["web"] = row["website"]
        if pd.notna(row["email"]):
            props["email"] = row["email"]
        if pd.notna(row["phone"]):
            props["phone"] = row["phone"]
        # The map only needs the registry slug, to link to the publisher's
        # page; the id itself lives in the CSV.
        if pd.notna(row["iati_publisher_slug"]):
            props["iati"] = row["iati_publisher_slug"]
        props["countries"] = row["overseas_countries"]  # "; "-joined list
        features.append({
            "type": "Feature",
            # GeoJSON coordinate order is [longitude, latitude]
            "geometry": {
                "type": "Point",
                "coordinates": [round(row["longitude"], 5),
                                round(row["latitude"], 5)],
            },
            "properties": props,
        })
    return {
        "type": "FeatureCollection",
        # "meta" is a foreign member (allowed by the GeoJSON spec); the map
        # page reads it to label the snapshot and show the preview banner.
        "meta": {
            # --snapshot pins the date when re-assembling an existing
            # snapshot, so the published date does not silently change.
            "snapshot": snapshot or str(date.today()),
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
    parser.add_argument("--snapshot", default=None,
                        help="set meta.snapshot (YYYY-MM-DD). Default: keep "
                             "the date already published in the map data; "
                             "pass this when assembling a NEW snapshot")
    args = parser.parse_args()

    # Re-assembling the same underlying data (the usual case) must not
    # silently re-stamp the published snapshot date, so by default we carry
    # the date forward from the map file we are about to overwrite.
    if args.snapshot is None and MAP_DATA_OUT.exists():
        with open(MAP_DATA_OUT) as f:
            args.snapshot = json.load(f).get("meta", {}).get("snapshot")
        print(f"keeping published snapshot date {args.snapshot} "
              "(pass --snapshot to change)")

    if not args.tags.exists():
        raise SystemExit(f"{args.tags} not found - run the tagging stage "
                         "first (or pass --tags with a sample).")

    geocoded = pd.read_csv(GEOCODED_PATH)

    # Attach the contact columns from the filter stage's output. They are
    # read from international.csv rather than the geocoded file so the
    # frozen geocoding output never needs regenerating. dtype=str keeps
    # phone numbers' leading zeros ("020..." must not become 20...).
    # If a future full rerun carries the columns through geocode.py, drop
    # them first so the merge cannot create duplicate _x/_y columns.
    geocoded = geocoded.drop(
        columns=[c for c in CONTACT_COLS if c in geocoded.columns])
    contacts = pd.read_csv(INTL_PATH,
                           usecols=["organisation_number"] + CONTACT_COLS,
                           dtype={c: str for c in CONTACT_COLS})
    geocoded = geocoded.merge(contacts, on="organisation_number", how="left")

    # Cleaned, publishable versions; the register-verbatim values stay in
    # international.csv.
    geocoded["website"] = geocoded["charity_contact_web"].map(clean_website)
    geocoded["email"] = geocoded["charity_contact_email"].map(clean_email)
    geocoded["phone"] = geocoded["charity_contact_phone"].map(clean_phone)
    geocoded = geocoded.drop(columns=CONTACT_COLS)
    for col in ["website", "email", "phone"]:
        ok = geocoded[col].notna().sum()
        print(f"usable {col}: {ok:,} of {len(geocoded):,} ({ok / len(geocoded):.1%})")

    # IATI publisher flag: a post-hoc join, never something the classifier
    # saw. Stored as the publisher's own organisation id ("GB-CHC-274467")
    # and left blank when the charity does not publish - a text column, not
    # a True/False one, so it survives being read back as strings later.
    if not IATI_PATH.exists():
        sys.exit(f"{IATI_PATH} not found - run .venv/bin/python src/fetch_iati.py "
                 "first (it needs no key and takes a few seconds).")
    # The dataset column is the id (what other datasets join on); the slug
    # is only needed to build the map's link to the publisher's page.
    iati = pd.read_csv(IATI_PATH, dtype=str,
                       usecols=["registered_charity_number", "iati_publisher_id",
                                "iati_publisher_slug"])
    geocoded = geocoded.drop(
        columns=[c for c in ["iati_publisher_id", "iati_publisher_slug"]
                 if c in geocoded.columns])
    # The charity number is an int in our table and text in the IATI file:
    # match on a text copy, then drop it, so the real column keeps its type.
    geocoded["_regno_str"] = geocoded["registered_charity_number"].astype(str)
    geocoded = geocoded.merge(
        iati.rename(columns={"registered_charity_number": "_regno_str"}),
        on="_regno_str", how="left").drop(columns="_regno_str")
    n_iati = geocoded["iati_publisher_id"].notna().sum()
    print(f"IATI publishers: {n_iati:,} of {len(geocoded):,} ({n_iati / len(geocoded):.1%})")

    tags = pd.read_csv(args.tags)
    df = build_dataset(geocoded, tags)

    if args.preview:
        print("preview mode: skipping the headline dataset CSV")
    else:
        # The slug is a map-only helper (see build_geojson); the dataset
        # carries the publisher id.
        df.drop(columns=["iati_publisher_slug"]).to_csv(CSV_OUT, index=False)
        print(f"Saved {len(df):,} rows to {CSV_OUT}")

    geojson = build_geojson(df, preview=args.preview, snapshot=args.snapshot)
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
