"""Build the machine-readable classification feed in feeds/findthatcharity/.

Why a feed at all: the dataset CSV is the right shape for analysts but not
for other sites that want to *ingest* the tags. findthatcharity.uk (Kane
Data's charity-lookup service, which already carries machine-generated
classifications with plain caveats) imports third-party
classifications from small CSVs at fixed raw-GitHub URLs: a code list per
vocabulary, plus one long-format file of (org_id, code) pairs. This script
reshapes the committed dataset into exactly that form, so anyone - not
only findthatcharity - can consume the tags without touching the pipeline.

The feed is ADDITIVE: it reads the committed outputs and writes a new
folder. It never changes the dataset, the map, or any published number.

Inputs (all committed, all produced by earlier stages):
  data/processed/uk_overseas_charities.csv   the dataset (assemble.py)
  data/processed/iati_publishers.csv         IATI publisher slugs (fetch_iati.py)
  data/manifest.json, data/iati_manifest.json  snapshot dates
  src/classify_prompt.py                     SDG_TITLES (the 17 official short titles)

Outputs (feeds/findthatcharity/):
  sdg_vocabulary.csv          code,title,uri            17 rows (UN SDG 1..17)
  engagement_vocabulary.csv   code,title,definition     3 rows
  classifications.csv         org_id,vocabulary,code,confidence
                                one row per (charity, vocabulary, code):
                                sdg_primary (1/charity) + sdg_secondary (0-2)
                                + overseas_engagement (1/charity)
  identifiers.csv             org_id,scheme,identifier,publisher_name,
                                registry_slug,url       the IATI publishers
  feed_manifest.json          version, provenance, accuracy framing,
                                licence, row counts, SHA-256 checksums
  (README.md in the same folder is written by hand, not by this script.)

Conventions, chosen to match what findthatcharity already ingests:
  - org_id is the org-id.guide form "GB-CHC-<registered charity number>";
    this dataset holds main charities only, so the number is unique.
  - UTF-8 without a byte-order mark, LF line endings, deterministic row
    order - so a re-run on unchanged inputs reproduces identical bytes and
    the checksums in the manifest stay valid.
  - in classifications.csv the vocabulary column is load-bearing: consumers
    must filter on it, or a plain org_id + code read would mix primary and
    secondary SDGs with the engagement codes. Only confidence is safely
    ignorable.

Run from the repo root:
    .venv/bin/python src/build_feed.py              # writes feed version 1.0.0
    .venv/bin/python src/build_feed.py --version 1.1.0
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
from classify_prompt import SDG_TITLES  # noqa: E402  (the 17 official short titles)

DATASET_PATH = REPO_ROOT / "data" / "processed" / "uk_overseas_charities.csv"
IATI_PATH = REPO_ROOT / "data" / "processed" / "iati_publishers.csv"
REGISTER_MANIFEST = REPO_ROOT / "data" / "manifest.json"
IATI_MANIFEST = REPO_ROOT / "data" / "iati_manifest.json"
OUT_DIR = REPO_ROOT / "feeds" / "findthatcharity"

REPO_URL = "https://github.com/jacksc09/uk-overseas-charities"
RAW_BASE = "https://raw.githubusercontent.com/jacksc09/uk-overseas-charities/main/feeds/findthatcharity"
ISSUES_URL = REPO_URL + "/issues/new"
MAP_URL = "https://jacksc09.github.io/uk-overseas-charities/"

ORG_ID_PREFIX = "GB-CHC-"
ORG_ID_RE = re.compile(r"^GB-CHC-\d+$")

# The three vocabularies, in the order rows are written. The slug is what an
# importer keys on; the title is what a site shows as a heading.
VOCABULARIES = {
    "sdg_primary": {
        "title": "UN Sustainable Development Goal (primary)",
        "file": "sdg_vocabulary.csv",
        "single": True,  # exactly one code per charity
    },
    "sdg_secondary": {
        "title": "UN Sustainable Development Goals (secondary)",
        "file": "sdg_vocabulary.csv",
        "single": False,  # zero, one or two codes per charity
    },
    "overseas_engagement": {
        "title": "Overseas engagement",
        "file": "engagement_vocabulary.csv",
        "single": True,
    },
}

# Engagement codes, titles and definitions. The definitions are the
# classifier's own (src/classify_prompt.py), lightly edited to read
# standalone; the labelling guide restated the same three categories.
ENGAGEMENT_CODES = [
    ("operates_directly_abroad", "Operates directly abroad",
     "The charity itself runs activities or has staff/projects in other countries."),
    ("funds_partners_abroad", "Funds partners abroad",
     "The charity mainly gives grants to or works through partner organisations overseas."),
    ("uk_fundraising_only", "UK fundraising only",
     "The charity raises money in the UK but its register text does not indicate "
     "that it operates or funds work abroad itself."),
]

# The UN's own linked-data URI for each goal (redirects to its SKOS record).
SDG_URI = "http://metadata.un.org/sdg/{code}"

# Frozen validation results, copied from outputs/validation/validation_results.md
# (blind, stratified n=150, seed 20260710, hand-labelled by the author on
# 2026-07-12). Kept here so the manifest can state them with their framing;
# if the validation is ever re-run, update both places.
VALIDATION = {
    "design": (
        "Stratified 150-charity sample (seed 20260710), frozen before labelling, "
        "hand-labelled blind by the author on 2026-07-12 from exactly the text the "
        "model saw. Accuracy means agreement with that single careful blind coder - "
        "a defensible benchmark, but a measure of deviation from one human's "
        "judgment rather than from objective ground truth."
    ),
    "primary_sdg_strict": {"accuracy": 0.773, "ci95": [0.700, 0.833], "n": 150,
                           "meaning": "model primary goal = hand label"},
    "primary_sdg_dual": {"accuracy": 0.787, "ci95": [0.714, 0.845], "n": 150,
                         "meaning": "or = the recorded equally-correct alternative"},
    "sdg_loose": {"accuracy": 0.940, "ci95": [0.890, 0.968], "n": 150,
                  "meaning": "hand label appears anywhere in primary + secondary goals"},
    "overseas_engagement_three_way": {"accuracy": 0.653, "ci95": [0.574, 0.725], "n": 150},
    "overseas_engagement_binary_post_hoc": {
        "accuracy": 0.833, "correct": 125, "n": 150, "ci95": [0.766, 0.884],
        "population_weighted": 0.852, "overseas_active_recall": 0.967,
        "meaning": "overseas-active (operates_directly_abroad + funds_partners_abroad) "
                   "vs uk_fundraising_only",
        "note": "POST HOC: added 2026-07-30, not pre-registered; a pure merge of the "
                "frozen labels scored by the same scorer.",
    },
    "uk_fundraising_only": {"precision": 0.927, "recall": 0.633},
    "known_failure_modes": [
        "The engagement flag over-calls overseas activity: about a third of the "
        "charities the labeller called uk_fundraising_only were promoted to an "
        "overseas-active class, and grant-funding relationships are often read as "
        "direct operation (21 of 54 hand-labelled funds_partners_abroad charities "
        "were tagged operates_directly_abroad). Treat the direct/partners boundary "
        "as soft; treat uk_fundraising_only as a reliable negative signal.",
        "Large UK-domestic charities whose register entry lists many countries but "
        "whose own text describes no overseas operations (RNLI, RSPB, universities) "
        "are filed under uk_fundraising_only by design - the classifier reads text "
        "only, never the register's area-of-operation fields.",
        "Think tanks and policy networks whose text is explicitly international but "
        "who advise or convene rather than run or fund projects abroad sit awkwardly "
        "in the three-way taxonomy.",
        "SDG 'low' confidence mostly marks sparse register text where a default rule "
        "(SDG 1) applies; do not read the low-confidence band's agreement rate as "
        "reliability.",
    ],
    "full_report": REPO_URL + "/blob/main/outputs/validation/validation_results.md",
    "protocol": REPO_URL + "/blob/main/METHODS.md",
}


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    """Commit of the inputs this feed was built from (short hash)."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"],
                             cwd=REPO_ROOT, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except Exception:  # not a git checkout, or git missing - still build
        return "unknown"


def write_csv(df: pd.DataFrame, path: Path) -> None:
    # utf-8 (no BOM) + LF: what csv.DictReader on the other end expects.
    df.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def build_sdg_vocabulary() -> pd.DataFrame:
    rows = [{"code": str(code), "title": title, "uri": SDG_URI.format(code=code)}
            for code, title in sorted(SDG_TITLES.items())]
    return pd.DataFrame(rows, columns=["code", "title", "uri"])


def build_engagement_vocabulary() -> pd.DataFrame:
    return pd.DataFrame(ENGAGEMENT_CODES, columns=["code", "title", "definition"])


def build_classifications(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (charity, vocabulary, code), in a stable order."""
    rows = []
    for _, r in df.iterrows():
        org_id = ORG_ID_PREFIX + r["registered_charity_number"]
        rows.append((org_id, "sdg_primary", r["primary_sdg"], r["sdg_confidence"]))
        # secondary_sdgs is "" or "4" or "1; 4" - split and strip. Emission
        # order is not preserved: the deterministic sort below normalises it,
        # which is fine because secondaries are documented as unranked.
        for code in [c.strip() for c in r["secondary_sdgs"].split(";") if c.strip()]:
            rows.append((org_id, "sdg_secondary", code, r["sdg_confidence"]))
        rows.append((org_id, "overseas_engagement", r["overseas_engagement"],
                     r["engagement_confidence"]))
    out = pd.DataFrame(rows, columns=["org_id", "vocabulary", "code", "confidence"])

    # Deterministic order: charity number, then vocabulary, then code.
    vocab_rank = {slug: i for i, slug in enumerate(VOCABULARIES)}
    out["_regno"] = out["org_id"].str.removeprefix(ORG_ID_PREFIX).astype(int)
    out["_vocab"] = out["vocabulary"].map(vocab_rank)
    out["_code"] = out["code"].apply(lambda c: int(c) if c.isdigit() else 99)
    out = (out.sort_values(["_regno", "_vocab", "_code", "code"], kind="mergesort")
              .drop(columns=["_regno", "_vocab", "_code"])
              .reset_index(drop=True))
    return out


def build_identifiers(df: pd.DataFrame, iati: pd.DataFrame) -> pd.DataFrame:
    """The charities that publish to the IATI Registry, as linked identifiers."""
    pubs = df.loc[df["iati_publisher_id"] != "", ["registered_charity_number", "iati_publisher_id"]]
    merged = pubs.merge(
        iati[["registered_charity_number", "iati_publisher_name", "iati_publisher_slug"]],
        on="registered_charity_number", how="left", validate="one_to_one",
    )
    out = pd.DataFrame({
        "org_id": ORG_ID_PREFIX + merged["registered_charity_number"],
        "scheme": "IATI",
        "identifier": merged["iati_publisher_id"],
        "publisher_name": merged["iati_publisher_name"],
        "registry_slug": merged["iati_publisher_slug"],
        # Public per-publisher page on the IATI Dashboard (the Registry
        # website itself stopped serving pages in December 2025).
        "url": "https://dashboard.iatistandard.org/publishers/" + merged["iati_publisher_slug"] + "/",
    })
    out["_regno"] = out["org_id"].str.removeprefix(ORG_ID_PREFIX).astype(int)
    return out.sort_values("_regno").drop(columns="_regno").reset_index(drop=True)


def check(condition: bool, message: str) -> None:
    """Print a tick or stop the run - the repo's stand-in for a test suite."""
    if not condition:
        sys.exit(f"  FAIL  {message}")
    print(f"  ok    {message}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", default="1.0.0",
                        help="feed version written to feed_manifest.json (semver)")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        sys.exit(f"--version must look like 1.0.0, got {args.version!r}")

    for p in (DATASET_PATH, IATI_PATH, REGISTER_MANIFEST, IATI_MANIFEST):
        if not p.exists():
            sys.exit(f"Missing input {p.relative_to(REPO_ROOT)} - run the pipeline "
                     "(assemble.py / fetch_iati.py) first.")

    df = pd.read_csv(DATASET_PATH, dtype=str, keep_default_na=False)
    iati = pd.read_csv(IATI_PATH, dtype=str, keep_default_na=False)
    register_meta = json.loads(REGISTER_MANIFEST.read_text(encoding="utf-8"))
    iati_meta = json.loads(IATI_MANIFEST.read_text(encoding="utf-8"))
    print(f"Loaded {len(df):,} charities from {DATASET_PATH.relative_to(REPO_ROOT)}")

    # --- input sanity: the things every downstream row depends on ------------
    print("\nInput checks")
    check(df["registered_charity_number"].is_unique, "registered_charity_number is unique")
    check(df["registered_charity_number"].str.fullmatch(r"\d+").all(), "charity numbers are digits")
    check(set(df["primary_sdg"]) == {str(i) for i in range(1, 18)}, "primary_sdg covers exactly 1..17")
    title_ok = all(SDG_TITLES[int(c)] == t for c, t in zip(df["primary_sdg"], df["primary_sdg_title"]))
    check(title_ok, "primary_sdg_title agrees with SDG_TITLES for every row")
    check(set(df["overseas_engagement"]) == {c for c, _, _ in ENGAGEMENT_CODES},
          "overseas_engagement uses exactly the three codes")
    check(set(df["sdg_confidence"]) <= {"high", "medium", "low"}
          and set(df["engagement_confidence"]) <= {"high", "medium", "low"},
          "confidence values are high/medium/low")
    check(df["tag_model"].nunique() == 1, f"single tag_model ({df['tag_model'].iloc[0]})")

    # --- build --------------------------------------------------------------
    sdg_vocab = build_sdg_vocabulary()
    eng_vocab = build_engagement_vocabulary()
    classes = build_classifications(df)
    idents = build_identifiers(df, iati)

    n_orgs = len(df)
    n_primary = (classes["vocabulary"] == "sdg_primary").sum()
    n_secondary = (classes["vocabulary"] == "sdg_secondary").sum()
    n_engage = (classes["vocabulary"] == "overseas_engagement").sum()
    expected_secondary = sum(len([c for c in s.split(";") if c.strip()]) for s in df["secondary_sdgs"])

    print("\nOutput checks")
    # The two literal counts below (19,688 charities, 200 IATI publishers)
    # pin this script to the committed snapshots (register 2026-07-09, IATI
    # 2026-08-15). A rebuild from a newer snapshot will fail them - update
    # the literals deliberately, alongside the version bump.
    check(n_orgs == 19688, "19,688 charities (committed 2026-07-09 snapshot)")
    check(len(sdg_vocab) == 17 and list(sdg_vocab["code"]) == [str(i) for i in range(1, 18)],
          "SDG vocabulary has codes 1..17 in order")
    check(len(eng_vocab) == 3, "engagement vocabulary has 3 codes")
    check(n_primary == n_orgs, f"primary-SDG rows = {n_primary:,} = number of charities")
    check(n_secondary == expected_secondary, f"secondary-SDG rows = {n_secondary:,} = non-empty secondary tags")
    check(n_engage == n_orgs, f"engagement rows = {n_engage:,} = number of charities")
    check(classes["org_id"].str.fullmatch(ORG_ID_RE.pattern).all(), "every org_id matches ^GB-CHC-\\d+$")
    check(classes["org_id"].nunique() == n_orgs, "classification rows cover every charity")
    check(not classes.duplicated(["org_id", "vocabulary", "code"]).any(),
          "no duplicate (org_id, vocabulary, code) rows")
    sdg_rows = classes[classes["vocabulary"].str.startswith("sdg")]
    check(set(sdg_rows["code"]) <= set(sdg_vocab["code"]), "every SDG code is in the SDG vocabulary")
    check(set(classes.loc[classes["vocabulary"] == "overseas_engagement", "code"]) == set(eng_vocab["code"]),
          "engagement codes are exactly the engagement vocabulary")
    prim = classes[classes["vocabulary"] == "sdg_primary"].set_index("org_id")["code"]
    sec = classes[classes["vocabulary"] == "sdg_secondary"]
    check(not (sec["code"].values == prim.reindex(sec["org_id"]).values).any(),
          "no secondary SDG repeats its charity's primary SDG")
    check(len(idents) == (df["iati_publisher_id"] != "").sum() == 200,
          f"IATI identifiers = {len(idents):,} (committed 2026-08-15 snapshot)")
    check((idents["identifier"] == idents["org_id"]).all(),
          "every IATI publisher id equals its org_id (GB-CHC form)")
    # notna() matters here: an unmatched left join would leave NaN, and
    # NaN != "" is True, so ne("") alone would wave the failure through.
    check(idents["registry_slug"].notna().all() and idents["registry_slug"].ne("").all()
          and idents["publisher_name"].notna().all() and idents["publisher_name"].ne("").all(),
          "every IATI row has a slug and a publisher name")

    # --- write --------------------------------------------------------------
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        "sdg_vocabulary.csv": sdg_vocab,
        "engagement_vocabulary.csv": eng_vocab,
        "classifications.csv": classes,
        "identifiers.csv": idents,
    }
    for name, frame in files.items():
        write_csv(frame, OUT_DIR / name)

    # Round trip: what we wrote reads back identically (and without a BOM).
    print("\nRound-trip checks")
    for name, frame in files.items():
        path = OUT_DIR / name
        check(path.read_bytes()[:3] != b"\xef\xbb\xbf", f"{name}: no byte-order mark")
        back = pd.read_csv(path, dtype=str, keep_default_na=False)
        check(back.equals(frame.reset_index(drop=True)), f"{name}: re-read equals what was written")

    checksums = {name: sha256_of(OUT_DIR / name) for name in files}
    manifest = {
        "feed": "uk-overseas-charities classifications for findthatcharity.uk",
        "version": args.version,
        "built_on": str(date.today()),
        "built_from_commit": git_head(),
        "repository": REPO_URL,
        "map": MAP_URL,
        "base_url": RAW_BASE,
        "publisher": {
            "name": "Jack Chen",
            "github": "jacksc09",
            "orcid": "https://orcid.org/0009-0000-4253-9010",
            "feedback": ISSUES_URL,
        },
        "licence": {
            "classifications": {
                "name": "CC0 1.0 Universal",
                "url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "note": "The SDG tags, engagement flags and confidence ratings are released "
                        "into the public domain. Attribution is appreciated but not required.",
            },
            "register_data": {
                "name": "Open Government Licence v3.0",
                "url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
                "note": "Charity numbers (and therefore org_ids) come from the Charity "
                        "Commission for England and Wales register extract.",
            },
            "iati_identifiers": {
                "note": "identifiers.csv uses publisher-identity metadata (name, identifier, "
                        "page slug) from the IATI Registry's public API; each publisher "
                        "declares its own licence for its data, recorded per publisher in "
                        "data/processed/iati_publishers.csv in the repository.",
            },
        },
        "provenance": {
            "register_snapshot": register_meta["downloaded_at_utc"][:10],
            "classification_run": "2026-07-10",
            "classification_method": (
                "Each charity's own register text (name, activities, charitable objects) "
                "was classified by a large language model (Claude Haiku 4.5, named once for "
                "reproducibility) into one primary and up to two secondary UN Sustainable "
                "Development Goals and a three-way overseas-engagement flag. The classifier "
                "never saw the register's area-of-operation fields. Sampling temperature was "
                "not fixed, so an identical re-run may differ slightly on borderline cases."
            ),
            "iati_snapshot": iati_meta["retrieved_at_utc"][:10],
            "charities": n_orgs,
            "input_dataset": {
                "path": "data/processed/uk_overseas_charities.csv",
                "sha256": sha256_of(DATASET_PATH),
            },
        },
        "vocabularies": {
            slug: {
                "title": v["title"],
                "codes_file": v["file"],
                "codes_url": f"{RAW_BASE}/{v['file']}",
                "single_code_per_charity": v["single"],
                "rows_in_classifications": int((classes["vocabulary"] == slug).sum()),
            }
            for slug, v in VOCABULARIES.items()
        },
        "files": {
            name: {
                "url": f"{RAW_BASE}/{name}",
                "rows": int(len(frame)),
                "columns": list(frame.columns),
                "sha256": checksums[name],
            }
            for name, frame in files.items()
        },
        "validation": VALIDATION,
    }
    (OUT_DIR / "feed_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("\nWrote")
    for name in list(files) + ["feed_manifest.json"]:
        path = OUT_DIR / name
        print(f"  {path.relative_to(REPO_ROOT)}  ({path.stat().st_size:,} bytes)")

    print("\nSpot check (Oxfam, GB-CHC-202918)")
    print(classes[classes["org_id"] == "GB-CHC-202918"].to_string(index=False))
    print(idents[idents["org_id"] == "GB-CHC-202918"].to_string(index=False))
    print(f"\nFeed version {args.version} built from commit {manifest['built_from_commit']}: "
          f"{n_orgs:,} charities, {len(classes):,} classification rows, {len(idents):,} identifiers.")


if __name__ == "__main__":
    main()
