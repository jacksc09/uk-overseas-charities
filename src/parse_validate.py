"""Parse, validate, and repair the raw tagging responses.

Reads data/raw/llm_responses.jsonl (from tag_batch.py fetch), checks every
response against the output schema plus consistency rules, and writes the
clean table to data/processed/sdg_tags.csv.

Anything malformed goes into a retry queue: one synchronous retry on the
bulk model, then escalation to the stronger model for whatever still fails.
This two-step repair is the pipeline's main failure-mode buffer - structured
outputs make hard failures rare, but refusals and truncations still happen.

Also prints the pre-registered sanity tripwires (from the project plan):
a warning if >25% of records are low-confidence, or if a single SDG
swallows an implausible share of the dataset.

Run from the repo root:  python src/parse_validate.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

import jsonschema
import pandas as pd

from classify_prompt import (
    BULK_MODEL,
    ESCALATION_MODEL,
    OUTPUT_SCHEMA,
    SDG_TITLES,
    build_request_params,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
RESPONSES_PATH = REPO_ROOT / "data" / "raw" / "llm_responses.jsonl"
CHARITIES_PATH = REPO_ROOT / "data" / "processed" / "international.csv"
OUT_PATH = REPO_ROOT / "data" / "processed" / "sdg_tags.csv"


def parse_one(text: str) -> dict:
    """Parse + validate one response; raises on anything off-spec."""
    parsed = json.loads(text)
    jsonschema.validate(parsed, OUTPUT_SCHEMA)
    # Consistency fixes the schema dialect can't express:
    # the title must match the number (trust the number, fix the title),
    # and the primary goal must not repeat inside the secondaries.
    parsed["primary_sdg_title"] = SDG_TITLES[parsed["primary_sdg"]]
    parsed["secondary_sdgs"] = [
        s for s in parsed["secondary_sdgs"] if s != parsed["primary_sdg"]
    ]
    return parsed


def retry_failures(failed_ids: list, charities: pd.DataFrame) -> dict:
    """Re-run failures synchronously: bulk model first, then escalate."""
    import os

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"\nNo API key available to retry {len(failed_ids)} failures - "
              "they are left untagged for now.")
        return {}

    import anthropic

    client = anthropic.Anthropic()
    by_id = charities.set_index(charities["organisation_number"].astype(str))
    repaired = {}
    for model in (BULK_MODEL, ESCALATION_MODEL):
        still_failed = [i for i in failed_ids if i not in repaired]
        if not still_failed:
            break
        print(f"Retrying {len(still_failed)} on {model}...")
        for cid in still_failed:
            row = by_id.loc[cid]
            params = build_request_params(
                row["charity_name"], row["charity_activities"],
                row["charitable_objects"], model=model,
            )
            try:
                response = client.messages.create(**params)
                text = next(
                    (b.text for b in response.content if b.type == "text"), ""
                )
                repaired[cid] = {"parsed": parse_one(text), "model": model}
            except Exception as e:  # noqa: BLE001 - log and move on
                print(f"  {cid} still failing on {model}: {e}")
    return repaired


def main() -> None:
    if not RESPONSES_PATH.exists():
        sys.exit("No raw responses found - run tag_batch.py fetch first.")

    charities = pd.read_csv(CHARITIES_PATH)
    rows, failed_ids = [], []
    with open(RESPONSES_PATH) as f:
        for line in f:
            record = json.loads(line)
            cid = record["custom_id"]
            ok = (record["result_type"] == "succeeded"
                  and record.get("stop_reason") == "end_turn")
            if ok:
                try:
                    rows.append((cid, parse_one(record["text"]),
                                 record.get("model", BULK_MODEL)))
                    continue
                except (json.JSONDecodeError, jsonschema.ValidationError):
                    pass
            failed_ids.append(cid)

    print(f"{len(rows):,} valid responses, {len(failed_ids):,} for retry.")
    if failed_ids:
        for cid, fix in retry_failures(failed_ids, charities).items():
            rows.append((cid, fix["parsed"], fix["model"]))

    tags = pd.DataFrame([
        {
            "organisation_number": int(cid),
            "primary_sdg": p["primary_sdg"],
            "primary_sdg_title": p["primary_sdg_title"],
            "secondary_sdgs": "; ".join(str(s) for s in p["secondary_sdgs"]),
            "focus_summary": p["focus_summary"],
            "sdg_confidence": p["sdg_confidence"],
            "overseas_engagement": p["overseas_engagement"],
            "engagement_confidence": p["engagement_confidence"],
            "tag_model": model,
        }
        for cid, p, model in rows
    ]).sort_values("organisation_number")
    tags.to_csv(OUT_PATH, index=False)
    print(f"Saved {len(tags):,} tag rows to {OUT_PATH} "
          f"(coverage: {len(tags) / len(charities):.1%} of charities)")

    # --- pre-registered tripwires ---------------------------------------
    low_share = (tags["sdg_confidence"] == "low").mean()
    print(f"\nlow sdg_confidence share: {low_share:.1%}"
          + ("  <-- WARNING: above the 25% tripwire!" if low_share > 0.25 else ""))
    sdg_counts = Counter(tags["primary_sdg"])
    top_sdg, top_n = sdg_counts.most_common(1)[0]
    top_share = top_n / len(tags)
    print(f"most common primary SDG: {top_sdg} ({SDG_TITLES[top_sdg]}) "
          f"at {top_share:.1%}"
          + ("  <-- check: is this dominance plausible?" if top_share > 0.5 else ""))
    print("\nengagement class counts:")
    print(tags["overseas_engagement"].value_counts().to_string())


if __name__ == "__main__":
    main()
