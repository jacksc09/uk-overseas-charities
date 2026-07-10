"""Validate (and eventually merge) the in-session classification outputs.

Companion to chunk_manual.py. Each chunk file is classified in its own
model session, which writes chunk_NNN.out.jsonl; this script is the
quality gate that decides when the run is actually done:

  .venv/bin/python src/check_manual_run.py               # progress report
  .venv/bin/python src/check_manual_run.py --make-retry  # re-queue failures
  .venv/bin/python src/check_manual_run.py --merge       # -> llm_responses.jsonl

Every output line must parse as JSON, match the official output schema
(via parse_validate.parse_one, the same check the API path gets), and
carry a custom_id that belongs to its chunk. Records from retry chunks
override earlier attempts for the same charity.

--merge only works at 100% valid coverage, and writes the records in the
exact shape tag_batch.py fetch would have produced, so parse_validate.py
and assemble.py run unchanged afterwards.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from chunk_manual import CHUNK_DIR, IN_PATH, INDEX_PATH, records_from_rows, write_chunk_file
from classify_prompt import SDG_TITLES
from parse_validate import parse_one

REPO_ROOT = Path(__file__).resolve().parent.parent
MERGE_PATH = REPO_ROOT / "data" / "raw" / "llm_responses.jsonl"


def load_outputs(index: dict):
    """Read every .out.jsonl and sort the records into valid/invalid.

    Returns (valid, invalid_lines, status) where valid maps custom_id ->
    {"output": raw dict, "model": model id}, invalid_lines is a list of
    (chunk, line_no, reason), and status maps chunk -> "done" / "partial"
    / "untouched". Chunks are processed in name order, so retry_* chunks
    come after chunk_* and later attempts override earlier ones.
    """
    valid, invalid_lines, status = {}, [], {}
    for name in sorted(index["chunks"]):
        entry = index["chunks"][name]
        expected = set(entry["ids"])
        out_path = CHUNK_DIR / entry["out"]
        if not out_path.exists():
            status[name] = "untouched"
            continue
        seen_here = set()
        for line_no, line in enumerate(out_path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                cid = str(record["custom_id"])
                if cid not in expected:
                    raise ValueError(f"custom_id {cid} not in this chunk")
                if cid in seen_here:
                    raise ValueError(f"custom_id {cid} repeated")
                # the same schema + consistency check the API path gets
                parse_one(json.dumps(record["output"]))
            except Exception as e:  # noqa: BLE001 - any defect = retry it
                invalid_lines.append((name, line_no, str(e)[:100]))
                continue
            seen_here.add(cid)
            valid[cid] = {
                "output": record["output"],
                # a line may carry its own model id (used when a stronger
                # model repairs single records); otherwise the chunk's
                "model": record.get("model", entry["model"]),
            }
        status[name] = "done" if seen_here == expected else "partial"
    return valid, invalid_lines, status


def print_report(index: dict, valid: dict, invalid_lines: list, status: dict):
    all_ids = {i for c in index["chunks"].values() for i in c["ids"]}
    missing = all_ids - set(valid)
    counts = Counter(status.values())
    print(f"Chunks: {counts['done']} done, {counts['partial']} partial, "
          f"{counts['untouched']} untouched (of {len(status)})")
    print(f"Charities: {len(valid):,} valid of {len(all_ids):,} "
          f"({len(valid) / len(all_ids):.1%}); {len(missing):,} still needed")
    if invalid_lines:
        print(f"\nInvalid output lines: {len(invalid_lines)} (first 10)")
        for chunk, line_no, reason in invalid_lines[:10]:
            print(f"  {chunk} line {line_no}: {reason}")
    todo = [n for n, s in status.items() if s != "done"]
    if todo:
        print(f"\nChunks still needing a run (first 12): {', '.join(todo[:12])}")

    if valid:
        # Early sight of the pre-registered tripwires, mid-run.
        outputs = [v["output"] for v in valid.values()]
        low = sum(o["sdg_confidence"] == "low" for o in outputs) / len(outputs)
        print(f"\nRunning distributions ({len(outputs):,} records so far):")
        print(f"  low sdg_confidence share: {low:.1%}"
              + ("  <-- above the 25% tripwire" if low > 0.25 else ""))
        for sdg, n in Counter(o["primary_sdg"] for o in outputs).most_common(5):
            print(f"  SDG {sdg:>2} {SDG_TITLES[sdg]:<38} {n / len(outputs):.1%}")
        for eng, n in Counter(o["overseas_engagement"] for o in outputs).items():
            print(f"  {eng:<28} {n / len(outputs):.1%}")
    return missing


def cmd_make_retry(index: dict, missing: set, model: str) -> None:
    """Pack every still-missing charity into fresh retry chunks."""
    if not missing:
        print("\nNothing to retry - all charities have valid outputs.")
        return
    df = pd.read_csv(IN_PATH)
    df = df[df["organisation_number"].astype(int).astype(str).isin(missing)]
    records = records_from_rows(df.sort_values("organisation_number"))
    n_existing = sum(1 for n in index["chunks"] if n.startswith("retry_"))
    made = []
    for start in range(0, len(records), 60):
        name = f"retry_{n_existing + len(made) + 1:03d}"
        entry = write_chunk_file(name, records[start:start + 60])
        entry["model"] = model  # attributed to whichever model runs it
        index["chunks"][name] = entry
        made.append(name)
    INDEX_PATH.write_text(json.dumps(index, indent=2))
    print(f"\nWrote {len(made)} retry chunk(s) for {len(records)} charities, "
          f"attributed to {model}: {', '.join(made)}")


def cmd_merge(index: dict, valid: dict, missing: set) -> None:
    """Write the merged results in tag_batch.py fetch's exact format."""
    if missing:
        print(f"\nRefusing to merge: {len(missing):,} charities still lack a "
              "valid output. Run --make-retry and classify those first.")
        return
    with open(MERGE_PATH, "w") as f:
        for cid in sorted(valid, key=int):
            f.write(json.dumps({
                "custom_id": cid,
                "result_type": "succeeded",
                "model": valid[cid]["model"],
                "stop_reason": "end_turn",
                "text": json.dumps(valid[cid]["output"]),
            }) + "\n")
    print(f"\nMerged {len(valid):,} records into {MERGE_PATH}")
    for model, n in Counter(v["model"] for v in valid.values()).items():
        print(f"  {model}: {n:,}")
    print("Next: .venv/bin/python src/parse_validate.py")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--make-retry", action="store_true",
                        help="write retry chunks for missing/invalid records")
    parser.add_argument("--model", default="claude-haiku-4-5",
                        help="model id to attribute retry chunks to")
    parser.add_argument("--merge", action="store_true",
                        help="write data/raw/llm_responses.jsonl (needs 100%%)")
    args = parser.parse_args()

    if not INDEX_PATH.exists():
        raise SystemExit("No chunk index - run src/chunk_manual.py first.")
    index = json.loads(INDEX_PATH.read_text())

    valid, invalid_lines, status = load_outputs(index)
    missing = print_report(index, valid, invalid_lines, status)
    if args.make_retry:
        cmd_make_retry(index, missing, args.model)
    if args.merge:
        cmd_merge(index, valid, missing)


if __name__ == "__main__":
    main()
