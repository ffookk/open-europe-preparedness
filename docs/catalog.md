# Offline policy catalog

Run `python3 -m scripts.catalog query FILE...` from the repository root using Python 3.10 or later. The command reads local UTF-8 JSON files only, validates every document with the existing structural validator and rejects duplicate IDs across files. No record is returned when any input fails validation. It does not fetch sources, assess policy truth or change data.

## Filters and review dates

```sh
python3 -m scripts.catalog query data/verified.json data/pending.json \
  --as-of 2026-09-20 --topic household_preparedness --status verified
python3 -m scripts.catalog query data/verified.json data/pending.json \
  --stage announced --stage adopted --record-type real --sort announced_at
python3 -m scripts.catalog query data/verified.json \
  --as-of 2026-09-20 --date-field announced_at --date-from 2025-01-01 --date-to 2025-12-31
```

- Repeat `--jurisdiction`, `--topic`, `--stage`, `--status` or `--record-type` for alternatives within that field. Different fields combine with AND. Jurisdictions match exact text without regard to case; the other filters use the schema vocabulary.
- `--text` searches a case-insensitive substring across all stored string values, including claims, sources, limitations, dates and change history. It does not interpret regular expressions or search remote pages.
- `--date-field` chooses `last_verified_at` (default), `announced_at`, `adopted_at`, `effective_at` or `target_at`. Date bounds are inclusive, use strict `YYYY-MM-DD` syntax and exclude unknown dates. An unbounded date filter does not infer missing dates.
- `--date-presence known` selects records with the chosen date; `unknown` explicitly selects missing dates. `unknown` cannot be combined with date bounds. The default is `any`.
- `--max-review-age DAYS` requires a known review date no more than that many calendar days before `--as-of`; equality passes. Unknown review dates never pass an age limit. A value of zero selects records reviewed on the cutoff day.
- `--as-of` fixes one inclusive validation ceiling for every input's review and source-access dates and the reference day for review age. It defaults to the current UTC day. Future policy targets remain possible. It is not a historical snapshot and does not establish what was legally true on that date.

A verified proposal remains a proposal. The current three real reviewed records have AI agent source review and no independent human certification. Synthetic records remain explicitly fictional even when their example review status is `verified`.

## Results and exports

The default JSON result contains `catalog_as_of`, `total_count`, `matched_count`, `returned_count`, `offset`, `limit`, `facets`, `records` and a scope notice. Facets count each category over all matched records before pagination. They count catalog entries, not independently verified policies. This wrapper is a query result, not a schema dataset.

`--sort` accepts the identity, title, category and date fields shown in `--help`. Sort order is locale-independent, with ascending ID ties. `--descending` reverses the primary key only. Missing dates sort last in both directions. `--offset` defaults to 0 and `--limit` to 25; pages contain at most 1000 records.

`--dataset` emits the current page as exactly `{"schema_version": 1, "records": [...]}`, preserving every field, evidence note, source and change-history entry. This can be validated or queried again. Empty dataset exports fail because the schema requires at least one record; empty query results remain valid and include zero counts. Shell redirection follows ordinary shell overwrite behavior: choose a new destination yourself, preferably under ignored `private-output/`.

**Exports intentionally include full record text and source URLs.** Structural validation is not privacy screening. Only load records you intend to inspect; review exports before sharing them. CLI errors omit raw input values and paths.

## Limits and Python use

The standard-library implementation accepts 1-16 files, at most 8 MiB of raw bytes per file and 10000 records in total. UTF-8 decoding, duplicate object keys and nonfinite JSON numbers are checked strictly. Query text is limited to 1000 characters. Inputs and existing validation defaults are unchanged.

```python
import datetime as dt
from scripts.catalog import Query, load_catalog

catalog = load_catalog(["data/verified.json"], as_of=dt.date(2026, 9, 20))
result = catalog.query(Query(policy_stage=("announced",), max_review_age=0))
```

The API returns defensive copies. `CatalogError` diagnostics are safe fixed text. Exit code 0 means success, 1 means input/query/output failure, and 2 means malformed command arguments. These outcomes establish structural conformance only.
