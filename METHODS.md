# Methods

A one-page summary of how the dataset was built and how the tags were
validated. Run instructions live in the [README](README.md); every step
described here is a script in `src/` that prints its own sanity checks.

## Aim

Identify every England & Wales registered charity that operates
internationally, and enrich each one with: a primary (and up to two
secondary) UN Sustainable Development Goal, a one-line focus summary, a
three-way flag for *how* it engages overseas, and a head-office geocode —
then publish an honest accuracy figure for the machine-generated tags.

## Source data and population

- **Register extract:** Charity Commission full-register download (JSON,
  Open Government Licence), snapshot **2026-07-09**. `data/manifest.json`
  records the source URLs and SHA256 checksums of the exact files used;
  the extract regenerates daily, so later downloads will differ slightly.
- **Population rule:** active main charities (`linked_charity_number == 0`)
  with at least one area-of-operation row of type "Country" outside the
  United Kingdom. Rows for Scotland, Northern Ireland, the Isle of Man,
  Jersey and Guernsey do not count as overseas; the Republic of Ireland
  does. Result: **19,688 charities**.
- **Geocoding:** head-office contact postcodes, bulk-matched via
  postcodes.io. 95.8% matched (18,860), 2.3% had no postcode, 1.9% did not
  match. Geocodes are the *registered office*, not where the charity works
  — for many small charities that office is a trustee's home.

## Classification

Each charity was classified by a large language model (Claude Haiku 4.5,
named here once for reproducibility) in a single call combining all tags.

- **Input:** the charity's registered name, its self-described activities
  text, and its charitable objects text (capped at 6,000 characters) —
  nothing else. The register's structured area-of-operation and
  classification fields were deliberately withheld so they remain
  independent signals for cross-validation.
- **Prompt:** a fixed rulebook, a reference sheet for all 17 SDGs, and six
  worked examples, identical for every charity (`src/classify_prompt.py`).
  The model returns JSON with the SDG tags, a sub-20-word summary, the
  engagement flag (`operates_directly_abroad` / `funds_partners_abroad` /
  `uk_fundraising_only`), and a high/medium/low confidence rating for both
  the SDG call and the engagement call.
- **Coverage and repair:** every response was validated against the JSON
  schema after the fact; malformed or missing responses were re-queued and
  re-run until coverage reached 100% of the 19,688 charities, all tagged by
  the same model. Sampling temperature was not fixed on the interactive
  transport used for this run, so an identical re-run may differ on
  borderline cases — a documented reproducibility limitation.
- **Pre-registered tripwires** (checked before accepting the run): low
  confidence above ~25% of records, or one SDG swallowing an implausible
  share. Observed: 11.7% low-confidence SDG calls, and the largest goal
  (SDG 1, No Poverty) at 29.4% — plausible for a population defined by
  overseas activity.

## Hand-validation protocol

The design was fixed, in code, before any labelling happened
(`src/make_validation_sample.py`), so the protocol could not bend to fit
the numbers.

- **Sample:** 150 charities, fixed seed 20260710 (the draw is verified
  deterministic). Strata: engagement class × SDG confidence (9 cells),
  allocated proportionally with a floor of 6 rows per cell so rare
  low-confidence cells are still measurable; within each cell rows spread
  across primary SDGs in proportion to the cell's own mix, and a final
  swap pass guarantees all 17 goals appear at least once. Each row carries
  a population weight (cell population ÷ cell sample count) so the scorer
  can undo the floor's oversampling and report a population-level estimate.
- **Labelling:** the author hand-labelled every row **blind** (the model's
  answers sat in a separate key file, never shown in the sheet), judging
  only from the same text the model saw, under written rules fixed in
  advance: an alternative goal may be recorded only for genuinely
  dual-purpose charities; `funds_partners_abroad` requires evidence of
  grants or partners; `operates_directly_abroad` requires the charity's own
  activity abroad; sparse cases default to `uk_fundraising_only` only when
  there is no overseas signal at all; every ambiguous call is logged with a
  one-line reason.
- **Metrics** (`src/score_validation.py`): primary-SDG accuracy on three
  pre-declared readings — *strict* (model primary = hand label), *dual*
  (or = the recorded alternative), *loose* (hand label anywhere in the
  model's primary + secondaries) — plus engagement accuracy with a full
  confusion matrix and per-class precision/recall/F1. Every headline number
  gets a Wilson 95% confidence interval and a population-weighted estimate
  (Kish effective sample size), and accuracy is split by the model's own
  confidence flags to test whether they mean anything.

**Results** (labelled 2026-07-12; full report in
`outputs/validation/validation_results.md`): strict primary-SDG accuracy
**77.3%** (116/150, 95% CI 70.0–83.3%; population-weighted 77.4%), dual
78.7%, loose 94.0%. Overseas engagement 65.3% overall (95% CI 57.4–72.5%;
population-weighted 66.6%), with a consistent error direction: the model
over-calls overseas activity. `uk_fundraising_only` has 92.7% precision but
63.3% recall, and the commonest single confusion is hand-labelled
`funds_partners_abroad` tagged as `operates_directly_abroad` (21/54). The
model's SDG confidence flag is informative (strict accuracy 81.2% at
"high" vs 56.7% at "medium"); the low-confidence band's 87.5% agreement
(n=24) largely reflects the shared sparse-text default rule (SDG 1 when no
concrete detail exists) rather than rich evidence, and should not be read
as reliability.

## Cross-validation against register fields

The register's self-reported classification tick-boxes ("Overseas
Aid/Famine Relief", "Makes Grants To Organisations") and its
count of overseas countries were never shown to the classifier, so they
give an independent — though noisy and self-reported — cross-check on the
engagement flag. Results are in the README's Validation section and
`outputs/validation/cross_validation.md`; they are reported as agreement
between two imperfect signals, not as accuracy.

## Limitations

1. Most charities in this population are small, with sparse register text;
   tags for them lean on thin evidence, which is what the confidence flags
   and the low-confidence accuracy split are for.
2. The map and geocodes show head-office location, not where work happens.
3. The register's "international" population includes large UK-domestic
   charities whose text shows no overseas work; the engagement flag's
   `uk_fundraising_only` class is the designed fallback for these, and the
   cross-validation shows the pattern (they list *more* register countries
   than the overseas-active classes, median 2 vs 1).
4. The register tick-boxes used for cross-validation are self-reported and
   patchy; disagreement is not automatically model error.
5. Tags from this run are not perfectly reproducible (temperature was not
   fixed); the prompt, code, sample, and key are all published so the
   validation itself is fully reproducible.

## Licence and attribution

Contains public sector information licensed under the Open Government
Licence v3.0. Register data: Charity Commission for England and Wales.
Postcode geocoding: postcodes.io — Contains OS data © Crown copyright and
database right 2026; contains Royal Mail data © Royal Mail copyright and
database right 2026; source: Office for National Statistics, licensed
under the Open Government Licence v3.0.
