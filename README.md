# UK Overseas Charities

An open dataset of the England & Wales registered charities that operate
internationally, built from the Charity Commission's public register extract,
geocoded to their head-office postcodes, and prepared for thematic
classification (UN Sustainable Development Goals plus a three-way overseas
engagement flag).

**Status: work in progress.** Data spine complete: 19,688 active
internationally operating charities identified from the 2026-07-09 register
snapshot, 95.8% geocoded (2.3% missing postcode, 1.9% unmatched). The full
classification run is complete (100% coverage, all 19,688 charities tagged);
accuracy against a hand-labelled sample will be reported before the dataset
is considered final, and all tags should be treated as provisional until
then.

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
   against a hand-labelled sample will be reported before the dataset is
   final.

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
outputs/           Smoke-test artefacts, figures, maps
```

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
