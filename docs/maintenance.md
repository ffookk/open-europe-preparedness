# Offline catalog maintenance

The maintenance workflow preserves complete records and makes proposed changes inspectable before human review. It does not fetch sources, change policy facts, alter source datasets or certify evidence. Use Python 3.10 or later from the repository root; only the standard library is required.

## End-to-end workflow

1. Validate and snapshot the current catalog with an explicit date cutoff:

   ```sh
   python3 -m scripts.maintenance snapshot data/verified.json data/pending.json \
     --as-of 2026-09-20 --output private-output/catalog-before.json
   ```

2. Prepare proposed corrections in local input files after reading the original evidence yourself. Preserve the specific claim, policy stage, evidence verification status, sources, limits and change history. Save those proposed inputs under ignored `private-input/`; this command does not perform that research or modify them.

3. Create a separate complete snapshot of the proposed collection:

   ```sh
   python3 -m scripts.maintenance snapshot private-input/proposed-records.json \
     --as-of 2026-09-22 --output private-output/catalog-after.json
   ```

4. Compare complete snapshots and generate an offline report:

   ```sh
   python3 -m scripts.maintenance compare \
     --before private-output/catalog-before.json --after private-output/catalog-after.json \
     --as-of 2026-09-22 --max-review-age 180 --max-source-age 90 \
     --output private-output/change-review.json --html private-output/change-review.html
   ```

5. Open the HTML locally. Inspect every relevant field change, both versions of the evidence, and each structural review reason. Download a filtered review packet to help prepare a correction PR. The packet is a review aid, not approval or a replacement for the contribution process. A person must still review the original sources and proposed corrections before publication.

A single current collection also supports maintenance without a comparison:

```sh
python3 -m scripts.maintenance review private-output/catalog-before.json \
  --as-of 2026-09-22 --max-review-age 180 --max-source-age 90 \
  --output private-output/review-queue.json --html private-output/review-queue.html
```

Reopen a saved review or comparison artifact safely with:

```sh
python3 -m scripts.maintenance report private-output/change-review.json \
  --output private-output/reopened-review.html
```

The `report` command revalidates the complete embedded snapshots and recomputes the diff, review queue, metadata and fingerprints before rendering. It never trusts stored summaries alone.

## Snapshot format and identity

A `catalog_snapshot` is a version-1 maintenance envelope containing a full schema collection, the fixed validation cutoff, record count, dataset fingerprint, per-record fingerprints, policy identifier, limitations and a snapshot fingerprint. Record IDs are sorted to make file order and input record order irrelevant. Every original record field is preserved, including source list order, limitations, null dates and change history.

Fingerprints are lowercase SHA-256 over compact JSON with sorted object keys and ASCII escapes. The dataset fingerprint covers the normalized collection; the snapshot fingerprint covers every other snapshot field. An altered validation cutoff changes snapshot identity even if no record changed. Verification recreates the expected envelope and compares every field and type, rather than accepting a recomputed outer hash alone. Numeric metadata uses bounded integers; record fields are text, nulls and collections, so browser JSON downloads preserve the canonical content identity without floating-point normalization.

**Hashes identify content consistency, not authenticity.** Someone can replace a claim and recompute all hashes. There are no signatures, authenticated authors, source fetches or independent truth checks. The cutoff describes the structural validation context; it is not evidence of what was legally true on that date. A reviewed proposal remains a proposal, and AI agent source review does not become human certification.

Snapshots require complete intended collections. Comparing a subset to a complete collection reports the omitted IDs as removed; it cannot determine whether that omission was intended. Duplicate IDs across input files are rejected. Existing input schema rules still require nonempty documents. An explicitly empty collection can be created separately when needed, without weakening those rules:

```sh
python3 -m scripts.maintenance snapshot --empty --as-of 2026-09-22 \
  --output private-output/empty-catalog.json
```

An empty snapshot is a valid maintenance envelope. Its empty collection is not a standalone dataset accepted by the existing nonempty policy-record schema.

## Deterministic change review

Records are matched by exact ID and classified as `added`, `removed`, `changed` or `unchanged`. Renaming an ID yields one removal and one addition. Those labels describe presence in supplied collections: **removed never means repealed, and added never means adopted**. The caller supplies the before/after roles; cutoffs do not authenticate chronology.

Every changed leaf is recorded using a JSON Pointer path with before/after values and explicit presence flags. Missing, null and empty containers are distinct. Lists are compared by position, so inserting or reordering sources produces index-level changes rather than an inferred source identity match. Original arrays remain intact in both embedded snapshots. Policy-stage and verification-status changes have separate transition flags and separate field paths; flags apply when the same ID is present in both collections, while additions/removals retain their full field-level presence changes.

The comparison also reports changed snapshot cutoff/count metadata. Unchanged records remain in the report and both complete snapshots remain embedded. Stored counts, per-record hashes, field changes, metadata, limits and queue reasons must all match recomputation on import.

## Structural review queue

The queue evaluates only the after snapshot, or the current snapshot for `review`. Its fixed `--as-of` defaults to that snapshot's validation cutoff and must not precede it. It never uses the browser clock. Review and source-access ages are calendar-day differences; an age equal to the limit passes, and only a strictly greater age produces a stale reason. The defaults are 180 days for both thresholds.

| Reason code | Structural condition |
|---|---|
| `pending_review` | Evidence verification status is pending. |
| `not_verified` | Verification status differs from verified, including pending. |
| `review_date_missing` | Last-review date is null. |
| `review_stale` | Known review date exceeds the configured age limit. |
| `source_access_missing` | A source's access date is null. |
| `source_access_stale` | A known source-access date exceeds its age limit. |
| `source_publication_missing` | A source's publication date is null. |
| `source_locator_missing` | A source lacks an evidence locator. |
| `source_support_missing` | A source lacks a statement of what it supports. |

Reasons retain exact field/source-index paths. Known stale dates include age and threshold; unknown dates are never given an inferred age. Reasons are independent and can overlap: a pending record may also have missing dates and evidence fields. Counts summarize reason occurrences, not severity or independent records. Publication dates are not used as freshness clocks, and policy stage never drives quality triage. The queue can flag an explicitly unknown but legitimate date for human attention; it does not demand invention of a replacement value. No reasons means only that these configured checks found none.

## Offline report and downloads

The HTML supports full-text search, change/jurisdiction/type/status/reason filters, independent policy-stage and review-status transition filters, sorting, pagination, matched-set reason counts, a queue-only view, before/after evidence details and printing. Status and jurisdiction filters use the after/current record, or the before version for a removal. Sources are displayed as literal text. Keyboard controls have labels and focus indicators; empty and failed display states are explicit. Printing expands the current page only.

- **Full review JSON** preserves the complete comparison or review artifact. It can be reverified by `report`.
- **Before/after snapshot JSON** preserves each complete snapshot and its fingerprints. These can be compared or reviewed again, including after a browser download.
- **Filtered review packet** includes every matching record across all pages, its full before/after evidence, field changes and queue reasons. Its distinct `maintenance_selection` type references the originating report hash but does not claim to be a full verified snapshot or a schema dataset. The maintenance importer intentionally does not accept it as one.

**All original inputs remain in the HTML and full-artifact downloads even when hidden by filters.** A filtered packet contains the selected records' complete evidence; filtering is not field redaction. Browser search/filter state is not saved, and query text is not included in packets. Review any artifact before sharing it.

The page uses no server, network calls, external assets, browser storage or telemetry. Its fixed inline script and stylesheet are authorized by exact Content Security Policy hashes. Embedded JSON escapes HTML delimiters; record values enter the DOM as literal text. Verification happens when the HTML is generated, not as a claim that the HTML file can never be edited later.

## Safe outputs, limits and failures

Maintenance artifacts default to ignored `private-output/`. Choose fresh names on every run. POSIX output creation uses held directory descriptors, no-follow traversal, exclusive temporary ownership and an atomic no-clobber link. Files receive `0600`; newly created directories receive `0700`. Existing targets, hard links, symbolic links, parent traversal and overlapping output destinations are refused. Existing input files cannot be overwritten.

All requested destinations are preflighted before writing. JSON and HTML are separate files, not one transaction: if a later filesystem race or write/cleanup failure occurs, an earlier completed output may remain even though the command returns failure. A cleanup failure can likewise leave a completed destination. No existing content is replaced; inspect the requested destination before retrying with a fresh name. Browser downloads follow the browser's own destination rules.

Catalog inputs retain the existing limits: at most 16 files, 8 MiB per file and 10000 records. Each imported or exported maintenance artifact, including HTML, is limited to 32 MiB; large pairs can exceed the report limit even when each snapshot fits individually. Strict UTF-8 JSON decoding rejects duplicate keys, nonfinite numbers and excessively deep malformed input. Diagnostics omit raw values and paths. Only explicit input files and necessary output-directory metadata are accessed.

Exit code 0 means completion, 1 means input/validation/output failure, and 2 means malformed arguments. Run `python3 -m scripts.maintenance --help` for command help. Existing validator and catalog defaults are unchanged.

## Additional report controls

- **Topic:** filter the after/current record by topic, using the before record for a removal.
- **Policy stage:** filter stored stages independently of evidence review status; a stage does not establish evidence quality.
