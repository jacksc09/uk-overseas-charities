"""Filter the register to internationally operating charities.

A charity qualifies as "internationally operating" if it has at least one
area-of-operation row of type "Country" that is genuinely outside the UK.
This mirrors how NGO Explorer and Clifford (2016) define the overseas
charity population, so our counts are comparable to published figures
(Clifford found 16,502 in March 2014, or 16,274 excluding minor
territories).

Output: data/processed/international.csv - one row per main charity, with
the text fields (activities + charitable objects) that later classification
steps will need.

Run from the repo root:  python src/filter_international.py
"""

from pathlib import Path

from load import load_table

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "data" / "processed" / "international.csv"

# "Country" rows that are still within the UK or its crown dependencies.
# Scotland and Northern Ireland have their own charity regulators (OSCR and
# CCNI) and are UK nations, not overseas. The crown dependencies are part of
# the British Isles; excluding them matches Clifford's stricter definition.
# Note: "Ireland" (the Republic) IS a foreign country and is kept.
NOT_OVERSEAS = {
    "Scotland",
    "Northern Ireland",
    "Isle Of Man",
    "Jersey",
    "Guernsey",
}


def main() -> None:
    charity = load_table("charity")
    aoo = load_table("area_of_operation")
    gov_doc = load_table("governing_document")

    # One row per charity: main-charity rows only (branches share the same
    # registered number but have linked_charity_number 1, 2, ...).
    charity = charity[charity["linked_charity_number"] == 0]

    # Show what the area types look like so the exclusion choices above are
    # visibly grounded in the actual data, not assumptions.
    print("geographic_area_type values:")
    print(aoo["geographic_area_type"].value_counts().to_string())

    overseas_rows = aoo[
        (aoo["geographic_area_type"] == "Country")
        & (~aoo["geographic_area_description"].isin(NOT_OVERSEAS))
    ]

    # Per charity: how many overseas countries, and which ones (kept as a
    # semicolon-joined list so the CSV stays one row per charity).
    per_charity = (
        overseas_rows.groupby("organisation_number")["geographic_area_description"]
        .agg(n_overseas_countries="count", overseas_countries=lambda s: "; ".join(sorted(s)))
        .reset_index()
    )
    print(f"\nCharities with >=1 overseas country row: {len(per_charity):,}")

    merged = charity.merge(per_charity, on="organisation_number", how="inner")

    # Active charities only for the headline dataset, but count what we drop
    # so the exclusion is reportable rather than silent.
    status_counts = merged["charity_registration_status"].value_counts()
    print("\nRegistration status of the overseas population:")
    print(status_counts.to_string())
    active = merged[merged["charity_registration_status"] == "Registered"].copy()
    print(f"\nDropped as not 'Registered': {len(merged) - len(active):,}")
    print(f"Active internationally operating charities: {len(active):,}")

    # Attach the charitable objects text (needed for classification later).
    objects = gov_doc[gov_doc["linked_charity_number"] == 0][
        ["organisation_number", "charitable_objects"]
    ]
    active = active.merge(objects, on="organisation_number", how="left")

    columns = [
        "organisation_number",
        "registered_charity_number",
        "charity_name",
        "charity_registration_status",
        "date_of_registration",
        "latest_income",
        "latest_expenditure",
        "charity_contact_postcode",
        "charity_activities",
        "charitable_objects",
        "n_overseas_countries",
        "overseas_countries",
    ]
    active[columns].to_csv(OUT_PATH, index=False)
    print(f"\nSaved {len(active):,} charities to {OUT_PATH}")

    # Quick sanity checks: a famous international charity must be present,
    # and the population should be roughly in the published 16k-20k range.
    oxfam = active[active["registered_charity_number"] == 202918]
    print(f"\nSpot check - Oxfam (202918) present: {len(oxfam) == 1}")
    if not 10_000 <= len(active) <= 30_000:
        print("WARNING: population size is far outside the expected range!")


if __name__ == "__main__":
    main()
