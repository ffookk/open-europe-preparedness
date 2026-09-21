# Validation CLI usage notes

The CLI only reads input files and reports validation results. It does not rewrite JSON or automatically correct records.

## Reproduce a date cutoff

Use `--as-of YYYY-MM-DD` to apply one inclusive date ceiling to `last_verified_at` and every source's `accessed_at` across all input files:

```sh
python3 scripts/validate_records.py --as-of 2026-09-20 data/verified.json data/pending.json examples/synthetic.json
```

Dates equal to the cutoff pass the ceiling check; later dates fail it. The option requires an exact calendar date, including a two-digit month and day. Invalid values produce a fixed diagnostic and exit code `2` without echoing the supplied value. If omitted, the CLI captures the current UTC date once for the entire command.

The cutoff does not rewrite records, fetch sources, establish policy truth at that date, or require target dates to have passed. Source access dates must still be no later than their record's `last_verified_at`. Python callers can supply the same ceiling with `validate_document(document, as_of=datetime.date(2026, 9, 20))`; existing calls default to the current UTC day.

## Optional reports and admission gates

- `--summary` appends fixed aggregate counts only after all inputs pass. It never includes record IDs, source URLs, paths or user text; counts do not establish factual verification.

- The `verification_states` summary includes all schema categories, with zero for absent categories.

- The `policy_stages` summary includes all schema categories, with zero for absent categories.

- The `topics` summary includes all schema categories, with zero for absent categories.

- `sources` reports total citations and counts with access dates, locators and support notes, without printing their contents.

- `source_domains` counts distinct hostnames after case and trailing-dot normalization. It does not list them or imply independent institutions.

- `jurisdictions` counts distinct exact jurisdiction labels. Different spellings remain distinct; labels are not printed.

- `policy_dates` counts non-null values for each policy date field; it does not evaluate policy implementation.

- `source_publication_dates` separates known and unknown citation publication dates; unknown dates remain null in the input.

- `--json` emits only the aggregate JSON object on success and implies a summary. Errors remain on stderr with a nonzero exit code.

- `--real-only` rejects synthetic records. Optional gate errors use `record-N`, numbered across the combined input order, without echoing IDs.

- `--require-reviewed` enforces the recorded status: pending records are rejected; other reviewed outcomes remain allowed. It does not certify human review.

- `--require-verified` enforces the recorded status: only verified records are allowed. It does not certify human review.

- `--require-source-locators` requires every source to have a non-null `locator` value, without filling missing metadata automatically.

- `--require-source-dates` requires every source to have a non-null `accessed_at` value, without filling missing metadata automatically.

- `--require-publication-dates` requires every source to have a non-null `published_at` value, without filling missing metadata automatically.

- `--require-source-support` requires every source to have a non-null `supports` value, without filling missing metadata automatically.

- `--min-sources N` sets a citation floor per record. Numeric policy values must be non-negative ASCII integers of at most nine digits; counts alone do not establish source independence.

- `--min-source-domains N` counts distinct normalized hostnames per record, not documents or independently controlled organizations.

- `--unique-sources` rejects duplicate exact URL strings within a record. URL aliases are not deduplicated; reuse across different records remains allowed.

- `--max-review-age DAYS` requires non-null `last_verified_at` dates no more than DAYS before the chosen cutoff. Equality passes; the original future-date restrictions still apply.

- `--max-access-age DAYS` requires non-null `accessed_at` dates no more than DAYS before the chosen cutoff. Equality passes; the original future-date restrictions still apply.

- `--min-records N` sets a combined input-record floor. Pending and synthetic records still count unless another requested gate excludes them.

- `--quiet` suppresses only the normal PASS banner. Requested summaries and validation errors remain visible.

- Standard input can be combined with files and all existing gates; it counts as one ordinal input and is subject to cross-input ID checks.

- `--version` reports the supported schema version and exits without requiring or reading input files.

- `--max-input-bytes N` applies a per-input UTF-8 byte ceiling to files and stdin. Equality passes. Files and binary stdin are read as raw bytes before UTF-8 decoding; text-only stdin streams are measured after UTF-8 encoding. No limit is imposed by default.

- `--max-errors N` limits displayed details, not validation work. An omitted-error count remains visible and the exit code stays nonzero; N=0 shows only that count.

- Python API callers receive generic schema errors for unknown keys even if their in-memory dictionary uses mixed key types.

- Excessively nested JSON produces the same value-free input failure instead of an uncaught decoder recursion traceback.

- The Python `as_of` argument must be a date object or None; strings and datetime objects receive a fixed validation error.

- Source URLs cannot contain ASCII control characters, including values a URL parser might otherwise discard.

## Inputs and diagnostics

- Provide at least one JSON file; omitting files produces a command-line usage error.
- A single `-` operand reads JSON from standard input. Multiple `-` operands are rejected before reading.
- Directories are not recursively expanded into JSON files. Explicitly list every file to validate together.
- Do not pass the same file twice. IDs encountered on the second read also trigger duplicate detection across inputs.
- If one input cannot be read, the CLI still attempts to check later inputs. Any error makes the overall command fail.
- Success summaries go to standard output; data diagnostics go to standard error. Capture more than standard output when collecting failure details.
- `input-2.records[0]` means the first record in the second command-line input. Input numbers start at 1; array indexes start at 0.
- JSON syntax errors include line and column numbers. Duplicate keys, encoding failures and file-read errors use generic messages that omit raw values.
- Whether an access or review date is in the future is determined against `--as-of`, or the current UTC date when it is omitted. Keep the UTC boundary in mind when entering dates across time zones.
- The record count in a `PASS` summary includes real, pending and synthetic records from every input. It is not a count of verified policies.
