"""Load the Charity Commission register extracts into pandas.

Each extract is a JSON array of row-objects. This module gives every later
script one shared way to read them (`load_table`), so parsing decisions
live in exactly one place.

Key facts about the register's structure, learned from the data itself:

- Rows are keyed on `registered_charity_number`, but that number is shared
  between a main charity and any "linked" charities (branches) it has.
  Main-charity rows have `linked_charity_number == 0`; branches have 1, 2, ...
  `organisation_number` is unique per row. When we want "one row per
  charity" we filter to `linked_charity_number == 0`.

- The files start with a UTF-8 byte-order mark, so we read them with
  encoding="utf-8-sig" (plain "utf-8" would leave junk on the first key).

Run directly to print the shape and columns of every table:
    python src/load.py
"""

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"

# Short aliases so later scripts can say load_table("charity") instead of
# spelling out the full publicextract filename every time.
TABLE_FILES = {
    "charity": "publicextract.charity.json",
    "area_of_operation": "publicextract.charity_area_of_operation.json",
    "annual_return_history": "publicextract.charity_annual_return_history.json",
    "annual_return_parta": "publicextract.charity_annual_return_parta.json",
    "annual_return_partb": "publicextract.charity_annual_return_partb.json",
    "governing_document": "publicextract.charity_governing_document.json",
    "classification": "publicextract.charity_classification.json",
}


def load_table(name: str) -> pd.DataFrame:
    """Load one register table by its short alias (see TABLE_FILES)."""
    path = RAW_DIR / TABLE_FILES[name]
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found - run 'python src/download.py' first."
        )
    # pd.read_json parses straight into a DataFrame without building a huge
    # intermediate list of dicts, which matters for the 1.2 GB part A file.
    return pd.read_json(path, encoding="utf-8-sig")


def main() -> None:
    for name in TABLE_FILES:
        df = load_table(name)
        print(f"\n=== {name} ===")
        print(f"shape: {df.shape[0]:,} rows x {df.shape[1]} columns")
        print(f"columns: {list(df.columns)}")


if __name__ == "__main__":
    main()
