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

A third signal was added post hoc on 2026-08-15 (it was not part of the
pre-registered protocol): whether the charity publishes to the IATI
aid-transparency registry (data/processed/iati_publishers.csv, from
fetch_iati.py). Publishing is a money-based fact the classifier never saw,
but it is one-sided - it says a charity is in the official aid-delivery
chain, while not publishing says nothing - and it covers only about 1% of
charities, the large ones. So it is a convergent check on a subset, not an
accuracy figure.

Writes outputs/validation/cross_validation.md and prints the same report.

Run from the repo root:  .venv/bin/python src/cross_validate.py
"""

from pathlib import Path

import pandas as pd

from load import load_table
from score_validation import wilson_ci

REPO_ROOT = Path(__file__).resolve().parent.parent
TAGS_PATH = REPO_ROOT / "data" / "processed" / "sdg_tags.csv"
TEXT_PATH = REPO_ROOT / "data" / "processed" / "international.csv"
IATI_PATH = REPO_ROOT / "data" / "processed" / "iati_publishers.csv"
OUT_PATH = REPO_ROOT / "outputs" / "validation" / "cross_validation.md"

OVERSEAS_AID = "Overseas Aid/famine Relief"
GRANTS_ORGS = "Makes Grants To Organisations"

# Why each IATI publisher that the model called uk_fundraising_only landed
# there, judged from the same register text the model saw. Two kinds:
#   text-sparse         - the text describes UK-focused or generic work with
#                         no overseas mechanism, so the flag's documented
#                         fallback applied (the RNLI-type case)
#   policy-intermediary - a think tank / network / policy body whose text
#                         IS explicitly international, but which advises,
#                         convenes or researches rather than running or
#                         funding projects abroad - a genuine boundary case
#                         for the three-way taxonomy
# Any publisher not listed here is reported as "unclassified" so a new
# snapshot can't silently misfile it.
DISAGREEMENT_NOTES = {
    "207076": "text-sparse",         # RSPB - UK conservation, no overseas mechanism
    "209603": "text-sparse",         # RNLI - sea rescue at home
    "213280": "text-sparse",         # RCOG - professional college
    "270901": "text-sparse",         # Education Development Trust - generic
    "313392": "text-sparse",         # NFER - education research
    "1133342": "text-sparse",        # ZING - grants to youth orgs, no place named
    "1150993": "text-sparse",        # Near East Foundation UK - generic objects,
                                     #   no country or mechanism in the text
    "210639": "policy-intermediary", # RUSI - defence & security think tank
    "228248": "policy-intermediary", # ODI Global - development think tank
    "298375": "policy-intermediary", # Centre for Lebanese Studies - research
    "1043843": "policy-intermediary",  # Saferworld - conflict-prevention NGO
    "1102909": "policy-intermediary",  # The Climate Group - business networks
    "1154413": "policy-intermediary",  # Climate Bonds Initiative - standards
}


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

    # --- signal 4 (post hoc): IATI publishers -----------------------------
    # Joined on registered_charity_number, which the tags table lacks, so
    # bring it (and income, for context) across from the text table first.
    df = df.merge(text[["organisation_number", "registered_charity_number",
                        "charity_name", "latest_income"]],
                  on="organisation_number", how="left")
    df["registered_charity_number"] = df["registered_charity_number"].astype(str)
    iati_pub = pd.read_csv(IATI_PATH, dtype=str,
                           usecols=["registered_charity_number", "iati_publisher_id"])
    df = df.merge(iati_pub, on="registered_charity_number", how="left")
    iati = df[df["iati_publisher_id"].notna()]
    n, k = len(iati), int(iati["llm_overseas_active"].sum())
    lo, hi = wilson_ci(k, n)
    small_share = (df["latest_income"] < 100_000).mean()
    lines += ["", "### IATI publishers vs model overseas-active "
              "(post hoc, one-sided)", "",
              "Added 2026-08-15, after the pre-registered protocol was "
              "scored, so it is a post-hoc check. IATI is the open standard "
              "aid organisations use to publish what they fund and where; "
              "publishing is often a condition of FCDO funding. Publishing "
              "therefore says a charity is in the official aid-delivery "
              "chain - not, strictly, that it runs projects abroad - and "
              "the check is one-sided: not publishing says nothing (most "
              "small charities have no reason to). It is also incomplete: "
              "only publishers who declare their charity number are matched, "
              "so charities that publish under a company number are not "
              "counted (they are listed in data/iati_manifest.json). It is a "
              "third convergent signal on a small, large-charity subset, not "
              "an accuracy figure; the hand-labelled sample remains the only "
              "accuracy measure.", "",
              f"Of the {n:,} charities in the dataset that publish to IATI "
              f"under their charity number "
              f"(median income £{iati['latest_income'].median():,.0f}, "
              f"against {small_share:.0%} of the whole population under "
              f"£100,000), the model calls {k:,} overseas-active: "
              f"**{k / n:.1%}** (Wilson 95% CI {lo:.1%}-{hi:.1%}).", "",
              "Model class among IATI publishers:", "```",
              iati["overseas_engagement"].value_counts().to_string(), "```", ""]

    # The disagreements, named and partitioned - they are informative
    # rather than embarrassing, and the two kinds mean different things.
    dis = iati[~iati["llm_overseas_active"]].copy()
    dis["kind"] = dis["registered_charity_number"].map(DISAGREEMENT_NOTES) \
        .fillna("unclassified")
    lines += [f"The {len(dis)} IATI publishers the model called "
              "uk_fundraising_only, judged from the same text the model saw:",
              ""]
    for kind, blurb in [
        ("text-sparse", "register text describes UK-focused or generic work "
                        "with no overseas mechanism - the flag's documented "
                        "fallback behaviour"),
        ("policy-intermediary", "text IS explicitly international, but the "
                                "charity advises, convenes or researches "
                                "rather than running or funding projects "
                                "abroad - a boundary case the three-way "
                                "taxonomy does not cleanly hold"),
        ("unclassified", "not yet reviewed - see DISAGREEMENT_NOTES in "
                         "cross_validate.py"),
    ]:
        sub = dis[dis["kind"] == kind]
        if sub.empty:
            continue
        lines += [f"- **{kind}** ({len(sub)}): {blurb}"]
        lines += [f"  - {r.charity_name.title()} ({r.registered_charity_number})"
                  for r in sub.sort_values("registered_charity_number").itertuples()]
    if (dis["kind"] == "unclassified").any():
        print("\nWARNING: unclassified IATI disagreements - review and add to "
              "DISAGREEMENT_NOTES:")
        for r in dis[dis["kind"] == "unclassified"].itertuples():
            print(f"  [{r.registered_charity_number}] {r.charity_name}")

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
