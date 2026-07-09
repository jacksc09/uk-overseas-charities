"""Download the Charity Commission full-register extract.

Fetches the daily JSON extracts we need, unzips them into data/raw/, and
writes data/manifest.json recording exactly which snapshot we downloaded
(date, URLs, SHA256 checksums). The raw files are gitignored because they
are large and regenerated daily; the manifest is committed so anyone can
tell precisely which day's data a given run of this pipeline used.

Run from the repo root:  python src/download.py
"""

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

# The Charity Commission publishes each register table as a separate zip.
# JSON rather than the tab-delimited txt: the txt files have had embedded
# newline/quoting quirks historically, and JSON parses unambiguously.
BASE_URL = "https://ccewuksprdoneregsadata1.blob.core.windows.net/data/json"

TABLES = [
    "publicextract.charity",                       # one row per (main or linked) charity
    "publicextract.charity_area_of_operation",     # where each charity says it works
    "publicextract.charity_annual_return_history", # which annual returns exist
    "publicextract.charity_annual_return_parta",   # annual return details, part A
    "publicextract.charity_annual_return_partb",   # annual return details, part B (overseas fields)
    "publicextract.charity_governing_document",    # contains the charitable objects text
    "publicextract.charity_classification",        # what/who/how categories (e.g. "Overseas Aid/Famine Relief")
]

# Note: the bulk download has no table for the annual return's overseas
# questions (countries of delivery, partner agreements, per-country spend).
# charity_classification is the closest published structured signal, which
# is why it is in the list above.

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
MANIFEST_PATH = REPO_ROOT / "data" / "manifest.json"


# Network downloads fail transiently all the time, so retry up to 4 times,
# doubling the wait each attempt (2s, 4s, 8s) before giving up for real.
@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=30))
def download_zip(table: str) -> Path:
    """Download one table's zip into data/raw/ and return its path."""
    url = f"{BASE_URL}/{table}.zip"
    zip_path = RAW_DIR / f"{table}.zip"
    print(f"  downloading {url}")
    # stream=True downloads in chunks instead of holding the whole file
    # (some extracts are hundreds of MB) in memory at once.
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1 << 20):  # 1 MB chunks
                f.write(chunk)
    return zip_path


def sha256_of(path: Path) -> str:
    """Checksum a file so the manifest can prove which bytes we used."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Charity Commission for England and Wales, full register download",
        "licence": "Open Government Licence v3.0",
        "files": [],
    }

    for table in TABLES:
        zip_path = download_zip(table)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(RAW_DIR)
            extracted_names = zf.namelist()
        manifest["files"].append({
            "table": table,
            "url": f"{BASE_URL}/{table}.zip",
            "zip_sha256": sha256_of(zip_path),
            "zip_bytes": zip_path.stat().st_size,
            "extracted": extracted_names,
        })

    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nManifest written to {MANIFEST_PATH}")
    print("\nFiles now in data/raw/:")
    for p in sorted(RAW_DIR.iterdir()):
        if p.name != ".gitkeep":
            print(f"  {p.name}  ({p.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
