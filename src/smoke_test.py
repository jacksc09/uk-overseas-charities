"""Smoke-test the classification prompt on 20 hand-picked charities.

Two modes:

  python src/smoke_test.py
      Free mode - builds the 20 exact API request payloads and writes them
      to outputs/smoke_payloads.json for offline review. No API key needed,
      nothing is spent.

  python src/smoke_test.py --live
      Runs the same 20 requests against the real API synchronously (costs a
      few pence) and validates every response against the output schema.
      Requires ANTHROPIC_API_KEY in .env. Run this once before the full
      batch to prove the request shape end-to-end.

The 20 are chosen to stress the prompt: well-known charities where the right
answer is obvious, sparse records with no activities text (the known hard
case), and a random slice of typical ones. The selection is seeded so every
run picks the same 20.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from classify_prompt import OUTPUT_SCHEMA, build_request_params

REPO_ROOT = Path(__file__).resolve().parent.parent
IN_PATH = REPO_ROOT / "data" / "processed" / "international.csv"
PAYLOADS_PATH = REPO_ROOT / "outputs" / "smoke_payloads.json"
LIVE_RESULTS_PATH = REPO_ROOT / "outputs" / "smoke_live_results.json"

# Well-known internationally operating charities - obvious ground truth.
KNOWN_NUMBERS = [
    202918,   # Oxfam
    213890,   # Save the Children
    288701,   # WaterAid
    1105851,  # Christian Aid
    220949,   # British Red Cross
    207544,   # Sightsavers
    265464,   # Muslim Aid (grant/partner model)
    290836,   # Plan International UK
]
SEED = 42


def pick_smoke_sample(df: pd.DataFrame) -> pd.DataFrame:
    """8 well-known + 6 sparse + 6 random typical charities (deduped)."""
    known = df[df["registered_charity_number"].isin(KNOWN_NUMBERS)]
    missing = set(KNOWN_NUMBERS) - set(known["registered_charity_number"])
    if missing:
        print(f"note: not in the international set, skipped: {sorted(missing)}")

    rest = df.drop(known.index)
    sparse = rest[rest["charity_activities"].isna()].sample(6, random_state=SEED)
    typical = rest.drop(sparse.index).sample(6, random_state=SEED)

    sample = pd.concat([known, sparse, typical]).head(20)
    return sample


def build_payloads(sample: pd.DataFrame) -> list:
    payloads = []
    for _, row in sample.iterrows():
        payloads.append({
            "organisation_number": int(row["organisation_number"]),
            "charity_name": row["charity_name"],
            "request_params": build_request_params(
                row["charity_name"],
                row["charity_activities"],
                row["charitable_objects"],
            ),
        })
    return payloads


def run_live(payloads: list) -> None:
    """Send the 20 requests for real and schema-check every response."""
    import os

    import anthropic
    import jsonschema
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit(
            "No ANTHROPIC_API_KEY found.\n"
            "Copy .env.example to .env and add your key, then re-run."
        )

    client = anthropic.Anthropic()
    results, failures = [], 0
    for p in payloads:
        response = client.messages.create(**p["request_params"])
        if response.stop_reason == "refusal":
            print(f"  REFUSED: {p['charity_name']}")
            failures += 1
            continue
        text = next(b.text for b in response.content if b.type == "text")
        record = {
            "organisation_number": p["organisation_number"],
            "charity_name": p["charity_name"],
            "raw_text": text,
        }
        try:
            parsed = json.loads(text)
            jsonschema.validate(parsed, OUTPUT_SCHEMA)
            record["parsed"] = parsed
            print(f"  ok: {p['charity_name'][:40]:<40} "
                  f"SDG {parsed['primary_sdg']:>2} {parsed['overseas_engagement']}")
        except (json.JSONDecodeError, jsonschema.ValidationError) as e:
            record["error"] = str(e)
            failures += 1
            print(f"  INVALID: {p['charity_name']} - {e}")
        results.append(record)

    LIVE_RESULTS_PATH.write_text(json.dumps(results, indent=2))
    print(f"\n{len(results) - failures}/{len(payloads)} valid. "
          f"Results in {LIVE_RESULTS_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true",
                        help="actually call the API (costs a few pence)")
    args = parser.parse_args()

    df = pd.read_csv(IN_PATH)
    sample = pick_smoke_sample(df)
    payloads = build_payloads(sample)

    PAYLOADS_PATH.write_text(json.dumps(payloads, indent=2))
    print(f"Wrote {len(payloads)} request payloads to {PAYLOADS_PATH}")
    for p in payloads:
        print(f"  {p['organisation_number']:>8}  {p['charity_name'][:60]}")

    if args.live:
        print("\nRunning live against the API...")
        run_live(payloads)


if __name__ == "__main__":
    main()
