"""Submit and collect the full tagging run via the Message Batches API.

The Batches API processes requests asynchronously at half the normal price,
which is what makes tagging all ~19,700 charities cheap. Usage:

  python src/tag_batch.py submit   # build + submit the batch (once)
  python src/tag_batch.py status   # check progress
  python src/tag_batch.py fetch    # download results when finished

Requires ANTHROPIC_API_KEY in .env (copy .env.example). Each command is
safe to re-run: submit refuses to double-submit, and fetch just re-downloads.
Raw responses land in data/raw/llm_responses.jsonl keyed by charity, so a
crash never forces a paid re-run; parsing happens later in parse_validate.py.
"""

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from classify_prompt import build_request_params

REPO_ROOT = Path(__file__).resolve().parent.parent
IN_PATH = REPO_ROOT / "data" / "processed" / "international.csv"
META_PATH = REPO_ROOT / "data" / "processed" / "batch_meta.json"
RESULTS_PATH = REPO_ROOT / "data" / "raw" / "llm_responses.jsonl"


def get_client():
    load_dotenv(REPO_ROOT / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit(
            "No ANTHROPIC_API_KEY found - nothing was submitted or spent.\n"
            "To run the batch: copy .env.example to .env, add your API key\n"
            "(a funded account is needed; the full run costs roughly $15-31),\n"
            "then re-run this command."
        )
    import anthropic

    return anthropic.Anthropic()


def build_requests(df: pd.DataFrame) -> list:
    """One batch request per charity; custom_id ties the answer back."""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    return [
        Request(
            # Results come back in arbitrary order - custom_id is the only
            # reliable way to match a response to its charity.
            custom_id=str(int(row["organisation_number"])),
            params=MessageCreateParamsNonStreaming(
                **build_request_params(
                    row["charity_name"],
                    row["charity_activities"],
                    row["charitable_objects"],
                )
            ),
        )
        for _, row in df.iterrows()
    ]


def cmd_submit() -> None:
    if META_PATH.exists():
        meta = json.loads(META_PATH.read_text())
        sys.exit(
            f"A batch was already submitted ({meta['batch_id']}).\n"
            "Use 'status' or 'fetch'. Delete data/processed/batch_meta.json "
            "only if you really mean to submit (and pay for) a new run."
        )
    df = pd.read_csv(IN_PATH)
    requests = build_requests(df)
    print(f"Built {len(requests):,} requests.")

    client = get_client()
    batch = client.messages.batches.create(requests=requests)
    META_PATH.write_text(json.dumps({
        "batch_id": batch.id,
        "submitted_at": str(batch.created_at),
        "n_requests": len(requests),
        "source": str(IN_PATH.name),
    }, indent=2))
    print(f"Submitted batch {batch.id} ({batch.processing_status}).")
    print("Most batches finish within an hour. Check with: "
          "python src/tag_batch.py status")


def cmd_status() -> None:
    meta = _require_meta()
    client = get_client()
    batch = client.messages.batches.retrieve(meta["batch_id"])
    counts = batch.request_counts
    print(f"Batch {batch.id}: {batch.processing_status}")
    print(f"  processing {counts.processing:,} | succeeded {counts.succeeded:,} "
          f"| errored {counts.errored:,} | canceled {counts.canceled:,} "
          f"| expired {counts.expired:,}")
    if batch.processing_status == "ended":
        print("Done - run: python src/tag_batch.py fetch")


def cmd_fetch() -> None:
    meta = _require_meta()
    client = get_client()
    batch = client.messages.batches.retrieve(meta["batch_id"])
    if batch.processing_status != "ended":
        sys.exit(f"Batch still {batch.processing_status} - try again later.")

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(RESULTS_PATH, "w") as f:
        for result in client.messages.batches.results(meta["batch_id"]):
            record = {"custom_id": result.custom_id,
                      "result_type": result.result.type}
            if result.result.type == "succeeded":
                message = result.result.message
                record["model"] = message.model
                record["stop_reason"] = message.stop_reason
                record["text"] = next(
                    (b.text for b in message.content if b.type == "text"), ""
                )
            f.write(json.dumps(record) + "\n")
            n += 1
    print(f"Wrote {n:,} raw responses to {RESULTS_PATH}")
    print("Next: python src/parse_validate.py")


def _require_meta() -> dict:
    if not META_PATH.exists():
        sys.exit("No batch submitted yet - run: python src/tag_batch.py submit")
    return json.loads(META_PATH.read_text())


if __name__ == "__main__":
    commands = {"submit": cmd_submit, "status": cmd_status, "fetch": cmd_fetch}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"Usage: python src/tag_batch.py [{'|'.join(commands)}]")
    commands[sys.argv[1]]()
