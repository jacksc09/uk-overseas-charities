"""Score the hand-labelled validation sample against the model's tags.

Reads the filled-in labelling sheet (outputs/validation/labelling_sheet.xlsx)
and the matching answer key (sample_key.csv), and reports the pre-registered
accuracy metrics. The hand labels are the ground truth throughout - where
they disagree, the model is wrong, not the labeller.

Metrics (adjudication rules fixed before labelling started):

- Primary SDG, three readings:
    strict  - model's primary goal equals the hand label
    dual    - ...or equals the labeller's alternative goal (my_alt_sdg is
              only for genuinely dual-purpose charities)
    loose   - the hand label appears anywhere in the model's primary +
              secondary goals
- Overseas engagement: overall accuracy, a 3x3 confusion matrix, and
  per-class precision/recall/F1 (the interesting failure modes live here).
- Every headline number gets a Wilson 95% confidence interval, and a
  population-weighted estimate that undoes the sample design's deliberate
  oversampling of small strata (weights come from the key file).
- Accuracy is also split by the model's own confidence flags, to check
  those flags actually mean something.

Refuses to run until every row has my_primary_sdg and my_engagement.

Run from the repo root:  .venv/bin/python src/score_validation.py
"""

import argparse
import math
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "outputs" / "validation"
DEFAULT_SHEET = OUT_DIR / "labelling_sheet.xlsx"
KEY_PATH = OUT_DIR / "sample_key.csv"
REPORT_PATH = OUT_DIR / "validation_results.md"

ENGAGEMENT_CLASSES = [
    "operates_directly_abroad",
    "funds_partners_abroad",
    "uk_fundraising_only",
]


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple:
    """Wilson 95% confidence interval for a proportion (plain arithmetic)."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def fmt_acc(correct: pd.Series, weights: pd.Series, label: str) -> str:
    """One line: raw accuracy with CI, plus the population-weighted view.

    The weighted CI uses the Kish effective sample size (n_eff = (sum w)^2
    / sum w^2), a standard approximation for how much information a
    weighted sample really carries.
    """
    n, k = len(correct), int(correct.sum())
    lo, hi = wilson_ci(k, n)
    w_acc = (correct * weights).sum() / weights.sum()
    n_eff = weights.sum() ** 2 / (weights ** 2).sum()
    w_lo, w_hi = wilson_ci(round(w_acc * n_eff), round(n_eff))
    return (f"{label:<8} {k}/{n} = {k / n:.1%}  (95% CI {lo:.1%}-{hi:.1%})"
            f"  | population-weighted {w_acc:.1%} "
            f"(~CI {w_lo:.1%}-{w_hi:.1%})")


def load_labels(sheet_path: Path) -> pd.DataFrame:
    df = pd.read_excel(sheet_path, sheet_name="labelling")
    # Dropdown entries can come back as text or numbers depending on how
    # Excel stored them; coerce both goal columns to nullable integers.
    for col in ("my_primary_sdg", "my_alt_sdg"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    df["my_engagement"] = df["my_engagement"].astype("string").str.strip()

    problems = []
    missing_sdg = df["my_primary_sdg"].isna() | ~df["my_primary_sdg"].isin(range(1, 18))
    missing_eng = ~df["my_engagement"].isin(ENGAGEMENT_CLASSES)
    for _, row in df[missing_sdg | missing_eng].iterrows():
        problems.append(f"  row {row['organisation_number']}: "
                        f"my_primary_sdg={row['my_primary_sdg']}, "
                        f"my_engagement={row['my_engagement']}")
    if problems:
        sys.exit(f"{len(problems)} rows are not finished (need a valid "
                 "my_primary_sdg 1-17 and my_engagement):\n"
                 + "\n".join(problems[:20])
                 + ("\n  ..." if len(problems) > 20 else ""))

    # An alternative goal identical to the primary carries no information.
    same = df["my_alt_sdg"] == df["my_primary_sdg"]
    if same.any():
        print(f"note: {same.sum()} rows have my_alt_sdg == my_primary_sdg; "
              "ignoring those alt labels")
        df.loc[same, "my_alt_sdg"] = pd.NA
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet", type=Path, default=DEFAULT_SHEET,
                        help="filled-in labelling sheet (xlsx)")
    args = parser.parse_args()
    if not args.sheet.exists():
        sys.exit(f"{args.sheet} not found - run make_validation_sample.py "
                 "first, then label it.")

    labels = load_labels(args.sheet)
    key = pd.read_csv(KEY_PATH)
    df = labels.merge(key, on="organisation_number", how="inner")
    if len(df) != len(key):
        sys.exit(f"sheet/key mismatch: {len(df)} joined rows vs "
                 f"{len(key)} in the key - was the sheet edited?")
    print(f"scoring {len(df)} hand-labelled rows "
          f"(seed {key['seed'].iloc[0]})\n")

    # --- primary SDG ------------------------------------------------------
    # model_secondary_sdgs is a "; "-joined string like "3; 1" (or empty)
    model_all_sdgs = df.apply(
        lambda r: {int(r["model_primary_sdg"])}
        | {int(s) for s in str(r["model_secondary_sdgs"]).split(";")
           if s.strip().isdigit()},
        axis=1)
    strict = df["model_primary_sdg"] == df["my_primary_sdg"]
    dual = strict | (df["model_primary_sdg"] == df["my_alt_sdg"])
    loose = pd.Series(
        [my in allowed for my, allowed in
         zip(df["my_primary_sdg"], model_all_sdgs)], index=df.index)

    w = df["weight"]
    lines = ["## Primary SDG accuracy", "```"]
    lines.append(fmt_acc(strict, w, "strict"))
    lines.append(fmt_acc(dual, w, "dual"))
    lines.append(fmt_acc(loose, w, "loose"))
    lines.append("```")

    lines += ["", "By the model's own SDG confidence (strict):", "```"]
    for conf in ("high", "medium", "low"):
        sub = df["model_sdg_confidence"] == conf
        if sub.any():
            k, n = int(strict[sub].sum()), int(sub.sum())
            lo, hi = wilson_ci(k, n)
            lines.append(f"{conf:<7} {k}/{n} = {k / n:.1%}  "
                         f"(95% CI {lo:.1%}-{hi:.1%})")
    lines.append("```")

    # --- engagement flag --------------------------------------------------
    eng_ok = df["model_overseas_engagement"] == df["my_engagement"]
    lines += ["", "## Overseas engagement accuracy", "```"]
    lines.append(fmt_acc(eng_ok, w, "overall"))
    lines.append("```")

    matrix = pd.crosstab(df["my_engagement"], df["model_overseas_engagement"]
                         ).reindex(index=ENGAGEMENT_CLASSES,
                                   columns=ENGAGEMENT_CLASSES, fill_value=0)
    lines += ["", "Confusion matrix (rows = hand label, cols = model):",
              "```", matrix.to_string(), "```"]

    lines += ["", "Per-class metrics (hand labels as truth):", "```"]
    for cls in ENGAGEMENT_CLASSES:
        tp = matrix.loc[cls, cls]
        pred = matrix[cls].sum()      # model said cls
        truth = matrix.loc[cls].sum()  # labeller said cls
        prec = tp / pred if pred else 0.0
        rec = tp / truth if truth else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        lines.append(f"{cls:<26} precision {prec:.1%}  recall {rec:.1%}  "
                     f"F1 {f1:.2f}  (n={truth})")
    lines.append("```")

    lines += ["", "By the model's own engagement confidence:", "```"]
    for conf in ("high", "medium", "low"):
        sub = df["model_engagement_confidence"] == conf
        if sub.any():
            k, n = int(eng_ok[sub].sum()), int(sub.sum())
            lo, hi = wilson_ci(k, n)
            lines.append(f"{conf:<7} {k}/{n} = {k / n:.1%}  "
                         f"(95% CI {lo:.1%}-{hi:.1%})")
    lines.append("```")

    report = "\n".join(lines)
    print(report)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report + "\n")
    print(f"\nSaved this report to {REPORT_PATH}")


if __name__ == "__main__":
    main()
