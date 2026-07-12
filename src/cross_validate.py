"""Cross-validate the engagement flag against the register's own fields.

The classifier only ever saw each charity's name, activities and objects
text - never the register's structured classification codes or its
area-of-operation countries. So checking the model's overseas_engagement
flag against those fields is a genuinely independent comparison: neither
signal could copy the other.

Two register signals are used (from publicextract.charity_classification):

  "Overseas Aid/famine Relief"     - the charity told the Commission its
                                     work includes overseas aid
  "Makes Grants To Organisations"  - the charity says it works by making
                                     grants to organisations

Neither is ground truth. They are self-reported, tick-box, and narrow
("Overseas Aid" misses e.g. a school-building charity abroad). Disagreement
is therefore NOT automatically a model error - this measures agreement
between two imperfect signals, and the hand-labelled sample
(score_validation.py) is what actually measures accuracy.

Writes outputs/validation/cross_validation.md and prints the same report.

Run from the repo root:  .venv/bin/python src/cross_validate.py
"""

from pathlib import Path

import pandas as pd

from load import load_table

REPO_ROOT = Path(__file__).resolve().parent.parent
TAGS_PATH = REPO_ROOT / "data" / "processed" / "sdg_tags.csv"
TEXT_PATH = REPO_ROOT / "data" / "processed" / "international.csv"
OUT_PATH = REPO_ROOT / "outputs" / "validation" / "cross_validation.md"

OVERSEAS_AID = "Overseas Aid/famine Relief"
GRANTS_ORGS = "Makes Grants To Organisations"


def cohen_kappa(matrix: pd.DataFrame) -> float:
    """Cohen's kappa: agreement beyond what chance alone would produce."""
    total = matrix.to_numpy().sum()
    observed = matrix.to_numpy().diagonal().sum() / total
    expected = sum(matrix.loc[c].sum() * matrix[c].sum()
                   for c in matrix.columns) / total ** 2
    return (observed - expected) / (1 - expected)


def two_by_two(a: pd.Series, b: pd.Series, a_name: str, b_name: str) -> list:
    """Agreement report for two True/False series: matrix, %, kappa."""
    matrix = pd.crosstab(a, b).reindex(index=[True, False],
                                       columns=[True, False], fill_value=0)
    matrix.index = [f"{a_name}=yes", f"{a_name}=no"]
    matrix.columns = [f"{b_name}=yes", f"{b_name}=no"]
    agree = (a == b).mean()
    kappa = cohen_kappa(pd.crosstab(a, b).reindex(
        index=[True, False], columns=[True, False], fill_value=0))
    return ["```", matrix.to_string(),
            f"\nraw agreement {agree:.1%}, Cohen's kappa {kappa:.2f}", "```"]


def main() -> None:
    tags = pd.read_csv(TAGS_PATH)
    print(f"tagged population: {len(tags):,} charities")

    # One row per (charity, classification code); keep main charities only
    # and reduce to two True/False flags per organisation number. Building
    # the flags over every charity that has ANY classification row lets us
    # tell "didn't tick these boxes" apart from "not in the table at all".
    cls = load_table("classification")
    cls = cls[cls["linked_charity_number"] == 0]
    codes = cls.groupby("organisation_number")["classification_description"]\
        .agg(set)
    flags = pd.DataFrame({
        "overseas_aid": codes.map(lambda s: OVERSEAS_AID in s),
        "grants_orgs": codes.map(lambda s: GRANTS_ORGS in s),
    })

    df = tags.merge(flags, on="organisation_number", how="left")
    no_class = df["overseas_aid"].isna().sum()
    df[["overseas_aid", "grants_orgs"]] = \
        df[["overseas_aid", "grants_orgs"]].fillna(False).astype(bool)
    print(f"charities with no classification rows at all: {no_class:,} "
          "(counted as not ticking either box)")

    # The model's flag collapsed to "any overseas activity at all?"
    df["llm_overseas_active"] = df["overseas_engagement"].isin(
        ["operates_directly_abroad", "funds_partners_abroad"])

    lines = ["## Cross-validation against register classification codes",
             "",
             f"Population: all {len(tags):,} tagged charities. The register "
             "codes are self-reported tick-boxes the classifier never saw; "
             "this is agreement between two imperfect signals, not a "
             "measure of accuracy.", ""]

    # --- signal 1: overseas aid vs any-overseas-activity -----------------
    lines += [f'### "{OVERSEAS_AID}" vs model overseas-active', ""]
    lines += two_by_two(df["llm_overseas_active"], df["overseas_aid"],
                        "model_active", "register_aid")
    aid = df[df["overseas_aid"]]
    lines += ["",
              f"Where the register box IS ticked (n={len(aid):,}), the model "
              f"calls the charity overseas-active "
              f"{aid['llm_overseas_active'].mean():.1%} of the time.",
              "Share of each model class that ticked the box "
              "(expect both overseas classes well above uk_fundraising_only):",
              "```",
              df.groupby("overseas_engagement")["overseas_aid"].mean()
              .map("{:.1%}".format).to_string(), "```", ""]

    # --- signal 2: grant-making vs funds_partners_abroad -----------------
    lines += [f'### "{GRANTS_ORGS}" vs model funds_partners_abroad', ""]
    lines += two_by_two(df["overseas_engagement"] == "funds_partners_abroad",
                        df["grants_orgs"], "model_funds", "register_grants")
    lines += ["",
              "Share of each model class that ticked the grant-making box "
              "(expect funds_partners_abroad highest):",
              "```",
              df.groupby("overseas_engagement")["grants_orgs"].mean()
              .map("{:.1%}".format).to_string(), "```", ""]

    # --- signal 3: how many countries the register lists ------------------
    # n_overseas_countries comes from the area-of-operation table, which the
    # classifier was also blind to.
    text = pd.read_csv(TEXT_PATH)
    df = df.merge(text[["organisation_number", "n_overseas_countries"]],
                  on="organisation_number", how="left")
    lines += ["### Register countries listed, by model class", "",
              "Mean and median number of overseas countries each class has "
              "in the register's area-of-operation table:", "```",
              df.groupby("overseas_engagement")["n_overseas_countries"]
              .agg(["mean", "median", "count"]).round(1).to_string(), "```"]

    report = "\n".join(lines)
    print("\n" + report)

    # --- spot check: a household name should land where expected ----------
    oxfam = text[text["registered_charity_number"] == 202918]
    if not oxfam.empty:
        orgno = oxfam["organisation_number"].iloc[0]
        row = df[df["organisation_number"] == orgno].iloc[0]
        print(f"\nspot check - {oxfam['charity_name'].iloc[0]} ({orgno}): "
              f"model={row['overseas_engagement']}, "
              f"register aid box={row['overseas_aid']}, "
              f"grants box={row['grants_orgs']}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(report + "\n")
    print(f"\nSaved report to {OUT_PATH}")


if __name__ == "__main__":
    main()
