# UK Overseas Charities

An open dataset of the England & Wales registered charities that operate
internationally, built from the Charity Commission's public register extract,
geocoded to their head-office postcodes, and prepared for thematic
classification (UN Sustainable Development Goals plus a three-way overseas
engagement flag).

**Status: complete and validated.** 19,688 active internationally operating
charities identified from the 2026-07-09 register snapshot, 95.8% geocoded
(2.3% missing postcode, 1.9% unmatched), 100% classified, and validated
against a blind hand-labelled sample of 150 charities: **77.3% primary-SDG
accuracy** (95% CI 70.0–83.3%) and 65.3% overseas-engagement accuracy
(95% CI 57.4–72.5%), with per-class detail in [Validation](#validation).

## What this repo does

1. **Download** the daily full-register extract from the Charity Commission
   (JSON, under the Open Government Licence).
2. **Load** the relevant tables into pandas.
3. **Filter** to active charities with at least one area of operation that is
   a country outside the UK (~16,000–20,000 expected).
4. **Geocode** head-office postcodes via the free
   [postcodes.io](https://postcodes.io) bulk API.
5. **Classify** every charity with a large language model (Claude Haiku 4.5,
   named here once for reproducibility): the most relevant UN Sustainable
   Development Goal, up to two secondary goals, a one-line focus summary, and
   a three-way flag for how the charity engages overseas (operates directly
   abroad / funds partners abroad / UK fundraising only).
   Classification uses only each charity's own register text (name,
   activities, charitable objects) so it stays independent of the register's
   structured area-of-operation fields, which are held back for
   cross-validation. The pipeline supports two transports with an identical
   prompt: the Batch API (with schema-enforced output) or interactive
   sessions over small chunk files. This dataset's tags come from the
   interactive route; every response was validated against the same JSON
   schema afterwards, and malformed or missing responses were re-queued
   until coverage reached 100%. Sampling temperature was not fixed on the
   interactive route, so an identical re-run may differ slightly on
   borderline cases — a documented reproducibility limitation. Accuracy
   against a blind hand-labelled sample is reported under
   [Validation](#validation).

Note on interpretation: the map/geocode shows each charity's **head-office
location**, not where it works. For many small charities the registered
office is a trustee's home.

## Repo structure

```
data/raw/          Raw register extracts + raw model responses (gitignored;
                   see data/manifest.json)
data/processed/    Cleaned, filtered outputs (committed)
src/               Pipeline scripts, run in order:
  download.py        fetch + unzip the register extract, write manifest
  load.py            load tables into pandas (shared by later steps)
  filter_international.py   keep active, internationally operating charities
  geocode.py         bulk-geocode HQ postcodes
  classify_prompt.py prompt, examples, and output schema (shared)
  smoke_test.py      20-charity prompt check (payloads free; --live hits API)
  tag_batch.py       submit / poll / fetch the full batch tagging run
  chunk_manual.py    split charities into chunk files for interactive tagging
  check_manual_run.py  validate chunk outputs, re-queue failures, merge
  parse_validate.py  schema-check every response, retry + escalate failures
  assemble.py        join tags + geocodes into the final CSV and GeoJSON
  make_validation_sample.py  draw the blind stratified hand-validation sample
  score_validation.py        score the hand labels against the model's tags
  cross_validate.py          compare the engagement flag with register fields
outputs/           Smoke-test artefacts and validation results
docs/              The interactive map (Leaflet, one static page)
```

The method, validation protocol, and limitations are written up in
[METHODS.md](METHODS.md).

## How to run

Stage 1 - data spine (no API key needed):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python src/download.py
python src/load.py
python src/filter_international.py
python src/geocode.py
```

Stage 2 - classification. Route A uses the Batch API (needs
`ANTHROPIC_API_KEY` in `.env` with API credits; the full run costs roughly
$15-31 at current batch prices):

```bash
python src/smoke_test.py --live   # 20-charity sanity check (pennies)
python src/tag_batch.py submit    # submit the full batch
python src/tag_batch.py status    # ...until it reports "ended" (~1 hour)
python src/tag_batch.py fetch     # download raw responses
```

Route B (the one this dataset used) runs the same prompt interactively, with
no API key: `chunk_manual.py` splits the charities into ~355 self-contained
chunk files, each chunk is classified in a supervised model session, and
`check_manual_run.py` validates every output line, re-queues failures with
`--make-retry`, and finally writes the same raw-responses file with
`--merge`:

```bash
python src/chunk_manual.py           # write chunk files + index
# ...classify each data/raw/manual_chunks/chunk_*.md in a model session...
python src/check_manual_run.py            # progress + validity report
python src/check_manual_run.py --make-retry  # re-queue failures (if any)
python src/check_manual_run.py --merge    # -> data/raw/llm_responses.jsonl
```

Either route ends the same way:

```bash
python src/parse_validate.py      # validate, retry, escalate
python src/assemble.py            # final CSV + GeoJSON
```

Reproducibility: `data/manifest.json` records the snapshot date, source URLs,
and SHA256 checksums of the exact extract files a given run used. The register
extract is regenerated daily, so re-running `download.py` on a later date will
produce slightly different counts.

## Data dictionary

`data/processed/uk_overseas_charities.csv` (produced by `assemble.py`), one
row per main registered charity:

| Column | Source | Description |
|---|---|---|
| `organisation_number` | register | Unique organisation id (join key) |
| `registered_charity_number` | register | Public charity number |
| `charity_name` | register | Registered name |
| `charity_registration_status` | register | Always "Registered" in this dataset |
| `date_of_registration` | register | Date first registered |
| `latest_income` / `latest_expenditure` | register | Latest reported £, mixed financial years |
| `charity_contact_postcode` | register | Head-office postcode (**not** where the charity works) |
| `charity_activities` | register | Self-described activities text |
| `charitable_objects` | register | Objects text from the governing document |
| `n_overseas_countries` | register | Count of non-UK "Country" area-of-operation rows |
| `overseas_countries` | register | Semicolon-joined list of those countries |
| `latitude` / `longitude` / `admin_district` | postcodes.io | HQ postcode geocode |
| `geocode_status` | derived | `ok` / `missing_postcode` / `unmatched` |
| `primary_sdg` (1–17) / `primary_sdg_title` | model | Most relevant UN Sustainable Development Goal |
| `secondary_sdgs` | model | Up to two further goals (semicolon-joined) |
| `focus_summary` | model | One-line plain-English focus |
| `sdg_confidence` | model | high / medium / low |
| `overseas_engagement` | model | `operates_directly_abroad` / `funds_partners_abroad` / `uk_fundraising_only` |
| `engagement_confidence` | model | high / medium / low |
| `tag_model` | derived | Which model produced the tags for this row |

`data/processed/charities.geojson` carries the geocoded, tagged subset as
Point features (name, number, primary SDG, engagement, summary) for mapping.

## Validation

All tags are machine-generated; two checks are reported so they can be
read with the right amount of trust. The full protocol is in
[METHODS.md](METHODS.md).

### Hand-labelled accuracy

A stratified 150-charity sample (seed 20260710, drawn and frozen — protocol,
strata and adjudication rules included — *before* labelling began) was
hand-labelled blind by the author on 2026-07-12, from exactly the text the
model saw. Full output in
[outputs/validation/validation_results.md](outputs/validation/validation_results.md);
protocol in [METHODS.md](METHODS.md).

**Primary SDG** (n=150; population-weighted figures undo the sample design's
oversampling of small strata and are almost identical):

| Reading | Accuracy | 95% CI |
|---|---|---|
| strict — model primary = hand label | **77.3%** | 70.0–83.3% |
| dual — or = the recorded equally-correct alternative | 78.7% | 71.4–84.5% |
| loose — hand label anywhere in model primary + secondaries | 94.0% | 89.0–96.8% |

For context, the closest published benchmark for automated whole-register
UK charity classification is UK-CAT's machine-learning classifier at 56%
accuracy — on a different taxonomy (ICNP/TSO), so the comparison is
indicative rather than exact.

**Overseas engagement**: 65.3% overall (95% CI 57.4–72.5%). Per-class, with
hand labels as truth:

| Class | Precision | Recall | F1 |
|---|---|---|---|
| operates_directly_abroad | 50.9% | 80.6% | 0.62 |
| funds_partners_abroad | 59.6% | 57.4% | 0.58 |
| uk_fundraising_only | 92.7% | 63.3% | 0.75 |

The errors have a clear direction: the model **over-calls overseas
activity**. When it says `uk_fundraising_only` it is almost always right
(92.7% precision), but it takes a third of the charities the labeller
called UK-only and promotes them to an overseas-active class, and it
often reads grant-funding relationships as direct operation (21 of 54
hand-labelled `funds_partners_abroad` charities were tagged
`operates_directly_abroad`). Treat the direct/partners boundary as soft;
treat a `uk_fundraising_only` tag as a reliable negative signal.

The model's confidence flags carry real signal for the SDG tags (strict
accuracy 81.2% where it said "high" vs 56.7% at "medium") with one caveat:
the apparently strong low-confidence figure (87.5%, n=24) mostly reflects
sparse-text rows where the pre-registered default rule (SDG 1 when no
concrete detail exists) applies to labeller and model alike, so agreement
there measures a shared convention rather than rich evidence.

### Cross-validation against register classification codes

The classifier's input was each charity's name, activities, and objects
text only — the register's structured fields were deliberately withheld —
so the register's self-reported classification tick-boxes give an
independent, if noisy, cross-check. Neither side is ground truth: this is
agreement between two imperfect signals, not a measure of accuracy. Full
tables are in
[outputs/validation/cross_validation.md](outputs/validation/cross_validation.md).

- **"Overseas Aid/Famine Relief" tick-box vs the model's overseas-active
  classes.** Where a charity ticked the box (n=4,869), the model calls it
  overseas-active (operating directly or funding partners) **82.3%** of the
  time. Agreement across all 19,688 charities is low (43.1%, Cohen's
  κ = 0.08) because the box is narrow — aid and famine relief specifically —
  while the engagement flag covers any overseas work, so many charities the
  model calls overseas-active never ticked it.
- **"Makes Grants To Organisations" tick-box vs `funds_partners_abroad`.**
  **67.7%** of charities the model calls `funds_partners_abroad` ticked the
  grant-making box, against 42.0% of `operates_directly_abroad` and 44.3%
  of `uk_fundraising_only` (raw agreement 60.6%, κ = 0.22) — the ordering
  the flag predicts.
- **A known failure direction, reported rather than hidden:** charities the
  model flags `uk_fundraising_only` list *more* overseas countries in the
  register than the overseas-active classes (median 2 vs 1). This is the
  documented fallback pattern: the register's international population
  includes large UK-domestic charities whose entries list many countries
  but whose own text describes no overseas operations, and the
  text-only classifier files them under `uk_fundraising_only`.

## Licence and attribution

- Contains public sector information licensed under the
  [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
- Register data is from the
  [Charity Commission for England and Wales](https://register-of-charities.charitycommission.gov.uk/en/register/full-register-download).
- Postcode geocoding uses [postcodes.io](https://postcodes.io), built on ONS
  and Ordnance Survey open data: Contains OS data © Crown copyright and
  database right 2026; contains Royal Mail data © Royal Mail copyright and
  database right 2026; source: Office for National Statistics licensed under
  the Open Government Licence v3.0.
