# UK Overseas Charities

An open dataset of the England & Wales registered charities that operate
internationally, built from the Charity Commission's public register extract,
geocoded to their head-office postcodes, and prepared for thematic
classification (UN Sustainable Development Goals plus a three-way overseas
engagement flag).

**Status: work in progress.** Data spine complete: 19,688 active
internationally operating charities identified from the 2026-07-09 register
snapshot, 95.8% geocoded (2.3% missing postcode, 1.9% unmatched).
Classification stage is next.

## What this repo does

1. **Download** the daily full-register extract from the Charity Commission
   (JSON, under the Open Government Licence).
2. **Load** the relevant tables into pandas.
3. **Filter** to active charities with at least one area of operation that is
   a country outside the UK (~16,000–20,000 expected).
4. **Geocode** head-office postcodes via the free
   [postcodes.io](https://postcodes.io) bulk API.

Note on interpretation: the map/geocode shows each charity's **head-office
location**, not where it works. For many small charities the registered
office is a trustee's home.

## Repo structure

```
data/raw/          Raw register extracts (gitignored; see data/manifest.json)
data/processed/    Cleaned, filtered outputs (committed)
src/               Pipeline scripts, run in order:
  download.py        fetch + unzip the register extract, write manifest
  load.py            load tables into pandas (shared by later steps)
  filter_international.py   keep active, internationally operating charities
  geocode.py         bulk-geocode HQ postcodes
outputs/           Figures, maps, and other derived artefacts
```

## How to run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python src/download.py
python src/load.py
python src/filter_international.py
python src/geocode.py
```

Reproducibility: `data/manifest.json` records the snapshot date, source URLs,
and SHA256 checksums of the exact extract files a given run used. The register
extract is regenerated daily, so re-running `download.py` on a later date will
produce slightly different counts.

## Data dictionary

*To be written when the final dataset is assembled.*

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
