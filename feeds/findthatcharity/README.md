# Classification feed for findthatcharity.uk

A small, stable, machine-readable copy of this project's classifications,
shaped for ingestion by other services — in the first instance
[findthatcharity.uk](https://findthatcharity.uk), Kane Data's
charity-lookup service, which already imports third-party classifications
from CSVs at fixed raw-GitHub URLs. Anyone else is welcome to use it the
same way. The feed is offered for ingestion; it has not been requested or
endorsed by findthatcharity.uk.

It covers the **19,688** active England & Wales charities that the
Charity Commission register (snapshot 2026-07-09) lists as operating in at
least one country outside the UK, and gives each one:

- a **primary UN Sustainable Development Goal** (exactly one of 17),
- up to two **secondary goals**,
- a three-way **overseas-engagement flag** (operates directly abroad /
  funds partners abroad / UK fundraising only),

plus, for the 200 charities that publish aid data to the IATI Registry
under their charity number, their **IATI publisher identifier** as a
linked identifier.

All tags were assigned by a large language model (Claude Haiku 4.5, named
here once for reproducibility) from each charity's own register text
(name, activities, charitable objects) and checked against a blind
hand-labelled sample; the accuracy figures and their framing are in
[`feed_manifest.json`](feed_manifest.json) and in the
[repository README](../../README.md#validation). Nothing here is endorsed
by the Charity Commission.

## Files

Base URL: `https://raw.githubusercontent.com/jacksc09/uk-overseas-charities/main/feeds/findthatcharity/`

| File | Rows | Columns | What it is |
|---|---|---|---|
| `sdg_vocabulary.csv` | 17 | `code,title,uri` | The code list for the two SDG vocabularies: `code` 1–17, the UN short title, and the UN's linked-data URI for the goal. |
| `engagement_vocabulary.csv` | 3 | `code,title,definition` | The code list for the engagement flag, with the classifier's own one-line definitions (lightly edited to read standalone). |
| `classifications.csv` | 63,887 | `org_id,vocabulary,code,confidence` | One row per (charity, vocabulary, code). The `vocabulary` column is load-bearing — consumers must filter on it, since the file holds all three vocabularies: `sdg_primary` (one row per charity), `sdg_secondary` (0–2 rows) and `overseas_engagement` (one row). Only `confidence` (the model's own high/medium/low rating) is safe to ignore. |
| `identifiers.csv` | 200 | `org_id,scheme,identifier,publisher_name,registry_slug,url` | The IATI publishers, as linked identifiers rather than classifications: `scheme` is always `IATI`, `identifier` is the publisher's IATI organisation id (the same `GB-CHC-…` string as `org_id`), `url` is the publisher's page on the IATI Dashboard. Informational for consumers other than findthatcharity (the id is the string findthatcharity already uses as the org id, so there is nothing new for it to link); the Dashboard sits behind bot protection, so `url` resolves in a browser but returns 403 to programmatic clients. |
| `feed_manifest.json` | — | — | Version, build date, the commit the inputs came from, snapshot dates, method, licence, row counts, SHA-256 checksums of the four CSVs, and the validation results with their exact framing. |

Conventions: `org_id` is the [org-id.guide](http://org-id.guide/) form
`GB-CHC-<registered charity number>` (main charities only, so the number is
unique); files are UTF-8 without a byte-order mark, LF line endings,
deterministic row order, so a rebuild on unchanged inputs is byte-identical
and the manifest checksums stay valid.

## Versioning and stability

- The URLs above are fixed: the feed lives on `main` and is rebuilt in
  place. Each release is also tagged `feed-vX.Y.Z`, so a consumer who wants
  a frozen copy can pin the tag in the raw URL, e.g.
  `https://raw.githubusercontent.com/jacksc09/uk-overseas-charities/feed-v1.0.0/feeds/findthatcharity/classifications.csv`.
- `feed_manifest.json` carries the version and the checksums. Semantic
  versioning: **major** = a column or vocabulary changes shape (an importer
  would need editing); **minor** = a new register snapshot or a
  re-classification (rows change, shapes do not); **patch** = corrections
  to individual rows or metadata.
- The feed is built by [`src/build_feed.py`](../../src/build_feed.py) from
  the committed dataset and prints its own checks (row counts, code sets,
  `org_id` format, no duplicates, round-trip re-read). It never changes the
  dataset, the map, or any published number.

## Vocabulary descriptions

These are the descriptions intended to sit above the tags wherever they
are shown (findthatcharity.uk renders a vocabulary's description as
markdown on each charity's page, the way it already does for the
machine-learning ICNP/TSO codes and the keyword-matched UK-CAT tags).

**UN Sustainable Development Goal (primary)** — slug `sdg_primary`, one code per charity

> The UN Sustainable Development Goal that best matches what the charity works on, assigned automatically by a large language model from the charity's own register text (name, activities and charitable objects), as part of the [UK Overseas Charities](https://github.com/jacksc09/uk-overseas-charities) project. In a blind hand-labelled sample of 150 charities the primary goal agreed with the human label 77.3% of the time (95% CI 70.0–83.3%), so individual tags may be incorrect. Only charities the register lists as operating overseas are covered. Wrong tags can be reported on the project's [issue tracker](https://github.com/jacksc09/uk-overseas-charities/issues/new).

**UN Sustainable Development Goals (secondary)** — slug `sdg_secondary`, zero to two codes per charity

> Up to two further UN Sustainable Development Goals for the charity's work, assigned automatically by a large language model from the charity's own register text (name, activities and charitable objects), as part of the [UK Overseas Charities](https://github.com/jacksc09/uk-overseas-charities) project. Read them as a short list of plausible goals rather than a ranking: in a blind hand-labelled sample of 150 charities the human's goal appeared among the charity's primary or secondary goals 94.0% of the time. Wrong tags can be reported on the project's [issue tracker](https://github.com/jacksc09/uk-overseas-charities/issues/new).

**Overseas engagement** — slug `overseas_engagement`, one code per charity

> How the charity's money or activity reaches other countries, assigned automatically by a large language model from the charity's own register text (name, activities and charitable objects), as part of the [UK Overseas Charities](https://github.com/jacksc09/uk-overseas-charities) project. The three codes: **operates_directly_abroad** (the charity itself runs activities or has staff/projects in other countries), **funds_partners_abroad** (the charity mainly gives grants to or works through partner organisations overseas), and **uk_fundraising_only** (the charity raises money in the UK but its register text does not indicate that it operates or funds work abroad itself).
>
> This flag is less reliable than the SDG tags: in a blind hand-labelled sample of 150 charities the three-way flag agreed with the human label 65.3% of the time (83.3%, 125/150, once the two overseas-active classes are merged — a post-hoc reading). The model over-calls overseas activity, so treat the boundary between "operates directly" and "funds partners" as soft, and treat "UK fundraising only" (92.7% precision) as the reliable signal. Wrong tags can be reported on the project's [issue tracker](https://github.com/jacksc09/uk-overseas-charities/issues/new).

## What the tags are not good for

- **Ground truth.** Accuracy means agreement with one careful blind human
  coder on a 17-class taxonomy, not objective truth; the reported error
  folds in ordinary human disagreement as well as model mistakes.
- **Fine engagement distinctions.** The direct/partners boundary is soft
  (the model reads grant-funding relationships as direct operation more
  often than the reverse). Collapse the two overseas-active classes when
  the distinction does not matter.
- **Where a charity works.** The tags say what a charity works on and how
  its money reaches other countries, not which countries; the register's
  own area-of-operation list covers that and is deliberately not an input.
- **Coverage of "UK-only" charities.** Large UK-domestic charities that the
  register nevertheless lists as operating overseas (RNLI, RSPB,
  universities) are filed under `uk_fundraising_only` by design — the
  classifier reads text only.
- **IATI as a negative.** A charity missing from `identifiers.csv` may still
  publish to IATI under a company number; absence says nothing.

Full validation tables: [outputs/validation/validation_results.md](../../outputs/validation/validation_results.md);
protocol: [METHODS.md](../../METHODS.md).

## Licence

- The classifications (SDG tags, engagement flags, confidence ratings) are
  released into the public domain under
  [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).
  Attribution is appreciated but not required.
- Charity numbers, and therefore `org_id`s, contain public sector
  information licensed under the
  [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
  (Charity Commission for England and Wales).
- `identifiers.csv` uses publisher-identity metadata (name, identifier,
  page slug) from the [IATI Registry](https://iatistandard.org/)'s public
  API; each publisher declares its own licence for its data, recorded per
  publisher in [`data/processed/iati_publishers.csv`](../../data/processed/iati_publishers.csv).

Questions and corrections: open an
[issue](https://github.com/jacksc09/uk-overseas-charities/issues/new).
