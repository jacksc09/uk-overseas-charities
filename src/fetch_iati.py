"""Fetch the list of IATI publishers and keep the ones that are E&W charities.

IATI (the International Aid Transparency Initiative) is the open standard
that aid organisations use to publish what they fund and where. Its public
registry lists every publishing organisation with a self-declared
organisation identifier; charities registered in England and Wales use the
form "GB-CHC-<registered charity number>", which is exactly our join key.

Publishing to IATI is a strong, money-based signal that an organisation is
in the official aid-delivery chain (it is often a condition of FCDO
funding) - not, strictly, that it runs projects abroad itself. The
classifier never saw it - it only read register text - so the flag is a
fully independent cross-check of the overseas-engagement column, and a
useful dataset field in its own right. It is ONE-SIDED: publishing places
a charity in the aid-delivery chain; not publishing says nothing (most
small charities have no reason to publish).

Two known gaps in the join, both documented in the README: (1) only
publishers who declare a GB-CHC id are matched - a charity that publishes
under its Companies House number (GB-COH-...) has a blank in the column
even though it publishes; (2) a publisher who declares a linked-charity
reference (GB-CHC-<number>-<n>) is a subsidiary of a main charity, and is
excluded rather than attributed to the main registration.

What this script does:
  1. Pages the registry's public API (no key, no cost).
  2. Saves the raw response verbatim to data/raw/ (gitignored) so the
     snapshot is frozen - the registry changes daily.
  3. Keeps GB-CHC publishers, normalises the charity number, and writes
     data/processed/iati_publishers.csv (committed).
  4. Writes data/iati_manifest.json recording when/what was fetched and
     the raw file's SHA-256, mirroring data/manifest.json's role.

Run from the repo root:  .venv/bin/python src/fetch_iati.py
Then re-run assemble.py so the column reaches the dataset and the map.

To re-process an already-frozen dump (e.g. after fixing the cleaning
rules) WITHOUT re-fetching - so the snapshot the docs cite stays fixed:
    .venv/bin/python src/fetch_iati.py --from-raw data/raw/iati_publishers_2026-08-15.json
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
OUT_PATH = REPO_ROOT / "data" / "processed" / "iati_publishers.csv"
MANIFEST_PATH = REPO_ROOT / "data" / "iati_manifest.json"
DATASET_PATH = REPO_ROOT / "data" / "processed" / "uk_overseas_charities.csv"

# The registry's website was replaced by IATI Account in December 2025 and
# no longer serves pages (read-only publisher info moved to the IATI
# Dashboard, below), but its CKAN API still serves the publisher list.
API_URL = "https://iatiregistry.org/api/3/action/organization_list"
PAGE_SIZE = 200
# Public per-publisher page, keyed by the registry's slug ("name" field).
PUBLISHER_PAGE = "https://dashboard.iatistandard.org/publishers/{slug}/"
USER_AGENT = "uk-overseas-charities-research/1.0 (open dataset; contact via GitHub)"

PREFIX = "GB-CHC-"


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=20))
def fetch_page(offset: int) -> list:
    """One page of publishers; retried with backoff on network hiccups."""
    resp = requests.get(
        API_URL,
        params={"all_fields": "true", "limit": PAGE_SIZE, "offset": offset},
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    if not body.get("success"):
        raise RuntimeError(f"API returned success=false at offset {offset}")
    return body["result"]


def fetch_all() -> list:
    """Page through the whole list (a short page means we've reached the end)."""
    publishers = []
    offset = 0
    while True:
        page = fetch_page(offset)
        publishers.extend(page)
        print(f"  fetched {len(publishers):,} publishers so far", end="\r")
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    print()
    return publishers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-raw", type=Path, default=None,
                        help="re-process this frozen raw dump instead of "
                             "fetching (keeps the documented snapshot fixed)")
    args = parser.parse_args()

    if args.from_raw:
        raw_path = args.from_raw
        raw_bytes = raw_path.read_bytes()
        publishers = json.loads(raw_bytes)
        # The snapshot date is the dump's, not today's. It is read back from
        # the manifest written when that dump was fetched - and only if the
        # manifest really describes THIS dump, otherwise the wrong date
        # would be stamped onto the output.
        manifest = json.loads(MANIFEST_PATH.read_text())
        if manifest.get("raw_file") != raw_path.name:
            sys.exit(f"{MANIFEST_PATH.name} describes {manifest.get('raw_file')!r}, "
                     f"not {raw_path.name!r} - cannot recover this dump's "
                     "retrieval date. Re-fetch instead, or restore the "
                     "manifest that matches the dump.")
        retrieved = datetime.strptime(
            manifest["retrieved_at_utc"],
            "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        print(f"re-processing frozen dump {raw_path.name} "
              f"(retrieved {retrieved:%Y-%m-%d})")
    else:
        try:
            publishers = fetch_all()
        except Exception as exc:  # network down, API changed, etc.
            sys.exit(f"Could not fetch the IATI publisher list ({exc}).\n"
                     "Check your connection and that "
                     f"{API_URL}?all_fields=true&limit=1 responds, then re-run.")
        retrieved = datetime.now(timezone.utc)
        # --- 1. freeze the raw response ---------------------------------
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        raw_path = RAW_DIR / f"iati_publishers_{retrieved:%Y-%m-%d}.json"
        raw_bytes = json.dumps(publishers, ensure_ascii=False, indent=1).encode("utf-8")
        raw_path.write_bytes(raw_bytes)
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    print(f"total publishers: {len(publishers):,}  (raw: {raw_path.name})")

    # --- 2. keep E&W charities and normalise the number -----------------
    # The identifier is self-typed by each publisher. Accept exactly
    # "GB-CHC-" + digits (surrounding whitespace ignored). A trailing
    # "-<n>" is the register's LINKED-charity reference (a subsidiary of
    # main charity <number>), not stray punctuation - those are reported
    # and skipped, never squashed into a fabricated number.
    #
    # Everything else is out of scope for this join, but NOT invisible: the
    # manifest records how many publishers use each other scheme, and lists
    # the other GB-registered ones (GB-COH = Companies House, GB-SC =
    # Scotland, GB-NIC = Northern Ireland, ...) by name, so a reader can
    # see which UK charities publish under an id this join cannot match.
    rows, skipped = [], []
    other_scheme_counts = {}   # e.g. {"GB-COH": 175, "US-EIN": 158, ...}
    other_gb_publishers = []   # name + declared id for the GB-* ones
    for p in publishers:
        raw_id = (p.get("publisher_iati_id") or "").strip()
        if not raw_id.upper().startswith(PREFIX):
            # Scheme = everything before the last "-<registration>" part,
            # e.g. "GB-COH-1234" -> "GB-COH"; unparseable ids count as "?".
            parts = raw_id.upper().rsplit("-", 1)
            scheme = parts[0] if len(parts) == 2 and parts[0] else "?"
            other_scheme_counts[scheme] = other_scheme_counts.get(scheme, 0) + 1
            if scheme.startswith("GB-"):
                other_gb_publishers.append(
                    {"declared_id": raw_id, "title": (p.get("title") or "").strip(),
                     "slug": p.get("name") or ""})
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", raw_id[len(PREFIX):].strip(),
                         re.IGNORECASE)
        if not m or m.group(2):
            why = "linked-charity reference" if m else "not GB-CHC-<digits>"
            skipped.append((raw_id, p.get("title"), why))
            continue
        # int() then str() gives the register's canonical form (no leading
        # zeros), which is what our registered_charity_number column holds.
        digits = str(int(m.group(1)))
        rows.append({
            "registered_charity_number": digits,
            "iati_publisher_id": PREFIX + digits,   # canonical form
            "iati_publisher_name": (p.get("title") or "").strip(),
            "iati_publisher_slug": p.get("name") or "",
            "iati_license_id": p.get("license_id") or "",
            "iati_id_as_declared": raw_id,          # exactly as typed
            "retrieved_utc": retrieved.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    df = pd.DataFrame(rows)
    print(f"GB-CHC publishers kept: {len(df):,}")
    for raw_id, title, why in skipped:
        print(f"  skipped {raw_id!r} ({title}): {why}")
    top_other = sorted(other_scheme_counts.items(), key=lambda kv: -kv[1])[:6]
    print("other schemes (not matched by this join): "
          + ", ".join(f"{s} {n}" for s, n in top_other) + ", ...")
    print(f"  of which other GB-registered publishers listed in the manifest: "
          f"{len(other_gb_publishers):,}")

    # A charity number must map to one publisher; if two registry entries
    # ever declare the same number, stop and look rather than guess.
    dupes = df[df["registered_charity_number"].duplicated(keep=False)]
    assert dupes.empty, f"duplicate charity numbers after normalisation:\n{dupes}"
    print("all normalised charity numbers unique")

    # --- 3. how many are in our dataset? --------------------------------
    if DATASET_PATH.exists():
        ours = pd.read_csv(DATASET_PATH, usecols=["registered_charity_number"],
                           dtype=str)["registered_charity_number"]
        matched = df["registered_charity_number"].isin(ours)
        print(f"matched to uk_overseas_charities.csv: {matched.sum():,} of {len(df):,} "
              f"({len(df) - matched.sum():,} are removed charities, outside the "
              "international filter, or stale ids)")
    else:
        print("note: uk_overseas_charities.csv not found - skipping the match count")

    # --- 4. spot checks ---------------------------------------------------
    for regno, label in [("274467", "ActionAid UK"), ("202918", "Oxfam")]:
        hit = df[df["registered_charity_number"] == regno]
        if hit.empty:
            print(f"{label} ({regno}): not an IATI publisher under GB-CHC")
        else:
            r = hit.iloc[0]
            print(f"{label} ({regno}): {r['iati_publisher_name']} -> "
                  + PUBLISHER_PAGE.format(slug=r["iati_publisher_slug"]))
    print("example page form:", PUBLISHER_PAGE.format(slug="<slug>"))

    # --- 5. write outputs ---------------------------------------------------
    df = df.sort_values("registered_charity_number").reset_index(drop=True)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"Saved {len(df):,} rows to {OUT_PATH}")

    manifest = {
        "retrieved_at_utc": retrieved.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "IATI Registry public API (CKAN), organization_list with all_fields",
        "endpoint": API_URL,
        "publisher_page_form": PUBLISHER_PAGE,
        "licence_note": ("Registry publisher metadata is open; each publisher "
                         "declares its own licence for its DATA (recorded in "
                         "the license_id column: a mix of CC, ODC and other "
                         "open/attribution licences, a few blank). Only "
                         "publisher identity fields (name, id, slug) plus that "
                         "declared licence are kept."),
        "total_publishers": len(publishers),
        "gb_chc_publishers": int(len(df)),
        "gb_chc_skipped": [{"declared_id": r, "title": t, "reason": w}
                           for r, t, w in skipped],
        # What this join cannot see: publishers registered under other
        # schemes. Counts for all of them; names for the other GB ones,
        # since some are E&W charities publishing under a company number.
        "other_scheme_counts": dict(sorted(other_scheme_counts.items(),
                                           key=lambda kv: -kv[1])),
        "other_gb_publishers_not_matched": other_gb_publishers,
        "raw_file": raw_path.name,
        "raw_sha256": raw_sha,
        "raw_bytes": len(raw_bytes),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Saved manifest to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
