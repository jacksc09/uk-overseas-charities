"""Prepare classification chunks for the no-API, in-session tagging run.

The paid path (tag_batch.py) sends every charity to the Batch API, which
needs a funded key. This is the free alternative: split the charities into
small "chunk" files that can each be classified in one supervised model
session (covered by a chat subscription, so no API spend).

Each chunk file is a self-contained instruction sheet: the same rules, SDG
reference and worked examples as the API path (imported from
classify_prompt.py, the single source of truth, so the prompt cannot
drift), followed by the charities and precise output instructions. A
session reads one chunk file and writes chunk_NNN.out.jsonl next to it;
check_manual_run.py then validates those outputs and merges them into the
same data/raw/llm_responses.jsonl the Batch API would have produced, so
parse_validate.py and assemble.py run unchanged.

Run from the repo root:  .venv/bin/python src/chunk_manual.py
"""

import json
import sys
from pathlib import Path

import pandas as pd

from classify_prompt import (
    _SDG_REFERENCE,
    _SYSTEM_CORE,
    _charity_text,
    BULK_MODEL,
    FEW_SHOTS,
    OBJECTS_CHAR_CAP,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
IN_PATH = REPO_ROOT / "data" / "processed" / "international.csv"
CHUNK_DIR = REPO_ROOT / "data" / "raw" / "manual_chunks"
INDEX_PATH = CHUNK_DIR / "index.json"

# Chunk sizing. A session has to read the whole chunk file in one or two
# Read calls, so we cap both the row count and the total text size. Most
# charities have ~760 characters of text, so chunks usually hit the row cap.
MAX_ROWS = 60
MAX_CHARS = 45_000

# The instruction block at the top of every chunk file. Written for a small
# model: explicit about the output format, with nothing left to guess.
INSTRUCTIONS = """\
# Charity classification chunk: {chunk_name}

You are classifying UK-registered charities. This file contains everything
you need: the task, the rules, a reference list, worked examples, and the
charities themselves. Do not read any other files.

## Your task

Classify EVERY charity listed at the bottom of this file, in order, using
your own judgement and only the rules below. Do NOT write a script or
program to do the classification - read each charity's text and decide
yourself.

When you have classified all {n} charities, use the Write tool to create
this exact file:

{out_path}

The file must contain exactly {n} lines - one line per charity, in the
same order as listed. Each line must be a single JSON object of this
exact shape (no extra keys, no missing keys):

{{"custom_id": "<the charity's custom_id>", "output": {{"primary_sdg": <integer 1-17>, "primary_sdg_title": "<official short title of that SDG>", "secondary_sdgs": [<zero, one or two integers 1-17, never repeating primary_sdg>], "focus_summary": "<one line, under 20 words>", "sdg_confidence": "<high, medium or low>", "overseas_engagement": "<operates_directly_abroad, funds_partners_abroad or uk_fundraising_only>", "engagement_confidence": "<high, medium or low>"}}}}

Rules for the output file:
- One JSON object per line. Nothing else: no markdown, no code fences,
  no blank lines, no commentary before or after.
- Every custom_id must appear exactly once, copied exactly as given.
- The charity list ends with an "END OF CHARITY LIST" marker. If you do
  not see that marker when you read this file, the Read was truncated:
  re-read the rest with the offset parameter BEFORE classifying anything.

## Classification rules

{system_core}

{sdg_reference}

## Worked examples

{examples}

## The charities to classify ({n} total)

"""

FOOTER = """\

END OF CHARITY LIST - {n} charities. Now classify all of them and write
{out_path} with exactly {n} lines as instructed at the top of this file.
"""


def render_examples() -> str:
    """The few-shot examples as plain worked input/output pairs."""
    parts = []
    # FEW_SHOTS is a flat list of user/assistant message pairs.
    pairs = list(zip(FEW_SHOTS[0::2], FEW_SHOTS[1::2]))
    for i, (user, assistant) in enumerate(pairs, start=1):
        parts.append(
            f"### Example {i}\n"
            f"Input:\n{user['content']}\n"
            f'Correct "output" object:\n{assistant["content"]}\n'
        )
    return "\n".join(parts)


def write_chunk_file(chunk_name: str, records: list) -> dict:
    """Write one chunk instruction file; return its index entry.

    `records` is a list of dicts with custom_id, name, activities, objects.
    Shared with check_manual_run.py, which uses it to build retry chunks.
    """
    out_path = CHUNK_DIR / f"{chunk_name}.out.jsonl"
    body = [
        INSTRUCTIONS.format(
            chunk_name=chunk_name,
            n=len(records),
            out_path=out_path,
            system_core=_SYSTEM_CORE,
            sdg_reference=_SDG_REFERENCE,
            examples=render_examples(),
        )
    ]
    for rec in records:
        body.append(
            f"### custom_id: {rec['custom_id']}\n"
            + _charity_text(rec["name"], rec["activities"], rec["objects"])
            + "\n"
        )
    body.append(FOOTER.format(n=len(records), out_path=out_path))
    (CHUNK_DIR / f"{chunk_name}.md").write_text("\n".join(body))
    return {
        "file": f"{chunk_name}.md",
        "out": out_path.name,
        "model": BULK_MODEL,
        "ids": [rec["custom_id"] for rec in records],
    }


def records_from_rows(df: pd.DataFrame) -> list:
    """CSV rows -> the cleaned record dicts the chunk writer expects."""

    def clean(value) -> str:
        # pandas gives NaN (a float) for empty CSV cells
        return "" if not isinstance(value, str) else value.strip()

    return [
        {
            "custom_id": str(int(row["organisation_number"])),
            "name": clean(row["charity_name"]),
            "activities": clean(row["charity_activities"]),
            # same cap as the API path, so both see identical text
            "objects": clean(row["charitable_objects"])[:OBJECTS_CHAR_CAP],
        }
        for _, row in df.iterrows()
    ]


def main() -> None:
    df = pd.read_csv(IN_PATH).sort_values("organisation_number")
    assert df["organisation_number"].is_unique, "duplicate organisation_number!"

    # Safety valve: re-chunking after sessions have already written
    # outputs would desync the index from the outputs on disk.
    if INDEX_PATH.exists() and list(CHUNK_DIR.glob("*.out.jsonl")):
        if "--force" not in sys.argv:
            sys.exit(
                "Chunk outputs already exist in data/raw/manual_chunks/.\n"
                "Re-chunking now would orphan them. Re-run with --force only "
                "if you really mean to start the classification run over."
            )

    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    records = records_from_rows(df)

    # Greedy packing: fill a chunk until it hits the row cap or the
    # character budget, then start the next one.
    chunks, current, current_chars = {}, [], 0
    for rec in records:
        size = len(rec["name"]) + len(rec["activities"]) + len(rec["objects"])
        if current and (len(current) >= MAX_ROWS or current_chars + size > MAX_CHARS):
            name = f"chunk_{len(chunks) + 1:03d}"
            chunks[name] = write_chunk_file(name, current)
            current, current_chars = [], 0
        current.append(rec)
        current_chars += size
    if current:
        name = f"chunk_{len(chunks) + 1:03d}"
        chunks[name] = write_chunk_file(name, current)

    INDEX_PATH.write_text(json.dumps({
        "source": IN_PATH.name,
        "total": len(records),
        "chunks": chunks,
    }, indent=2))

    # --- sanity checks ---------------------------------------------------
    n_in_chunks = sum(len(c["ids"]) for c in chunks.values())
    sizes = [len(c["ids"]) for c in chunks.values()]
    print(f"Wrote {len(chunks)} chunk files to {CHUNK_DIR}")
    print(f"Charities in chunks: {n_in_chunks:,} (source rows: {len(df):,})")
    print(f"Chunk sizes: min {min(sizes)}, max {max(sizes)}, "
          f"mean {n_in_chunks / len(chunks):.1f}")
    all_ids = {i for c in chunks.values() for i in c["ids"]}
    assert len(all_ids) == n_in_chunks == len(df), "id mismatch across chunks!"
    # Oxfam's organisation_number - the standing spot check for this dataset
    oxfam = next((n for n, c in chunks.items() if "202918" in c["ids"]), None)
    print(f"Spot check - Oxfam (202918) present: "
          f"{'yes, in ' + oxfam if oxfam else 'NO - INVESTIGATE'}")
    biggest = max((CHUNK_DIR / c["file"]).stat().st_size for c in chunks.values())
    print(f"Largest chunk file: {biggest / 1024:.0f} KB")
    print("\nNext: classify each chunk file in a model session, then run "
          ".venv/bin/python src/check_manual_run.py")


if __name__ == "__main__":
    main()
