# Offline review resolution packets

Use explicit local decisions to turn a complete catalog snapshot into a separate candidate collection. The workflow preserves the exact source and full before/after evidence, validates proposed records, and makes the result reproducible. It does not fetch sources, modify original files, approve evidence, or infer that a person reviewed anything. Python 3.10 or later and the standard library are sufficient.

## Prepare, edit, check and resolve

Start from a verified maintenance snapshot. This example uses only the existing fictional fixture:

```sh
python3 -m scripts.maintenance snapshot examples/synthetic.json \
  --as-of 2024-01-05 --output private-output/fictional-source.json

python3 -m scripts.resolution prepare \
  --source private-output/fictional-source.json --scope all \
  --as-of 2024-01-05 --output private-output/fictional-packet.json
```

The default scope is `queued`, which selects precisely the IDs flagged by the structural review queue. `--scope all` selects every record, including records with no queue reasons. `--max-review-age` and `--max-source-age` default to 180 calendar days and retain the maintenance queue's strictly-greater-than threshold semantics. The preparation cutoff defaults to the source snapshot cutoff and cannot precede it. Nothing depends on today's clock.

Open the packet in a local JSON editor. Change **only** the `action`, `rationale` and `proposed_record` fields inside `decisions`. Keep the complete list and every `id`. For example, replace the fictional fixture's pending decision with:

```json
{
  "id": "synthetic-example-proposal",
  "action": "keep",
  "rationale": "Preserve the fictional demonstration record for this candidate; this is not evidence approval.",
  "proposed_record": null
}
```

Every selected record starts with `action: "pending"`. All selected decisions must be explicitly completed; dropping an entry does not mean keep. Each completed decision requires a nonempty rationale of at most 2000 characters.

| Action | Meaning | Required proposed_record |
|---|---|---|
| `keep` | Preserve the source record exactly, without approving it or clearing queue reasons. | `null` |
| `remove` | Omit the record from the new candidate; never a claim that a policy was repealed. | `null` |
| `replace` | Use an explicitly supplied complete record after existing schema validation. | Full record with the exact same ID |
| `pending` | Unresolved draft; prevents check and resolution. | Starts as `null`; must choose a completed action before use. |

For a replacement, copy the corresponding `basis.targets[].before` record into `proposed_record`, then edit that copy. Preserve appropriate evidence, uncertainty and history yourself; the tool does not invent dates, append history entries, fill missing source details, or promote verification or policy stages. A replacement may explicitly propose such field changes, but they remain visible proposals. An identical replacement is allowed and reported as an explicit `replace` decision with an unchanged record.

Check the entire edited proposal without writing output:

```sh
python3 -m scripts.resolution check \
  --source private-output/fictional-source.json \
  --packet private-output/fictional-packet.json --as-of 2024-01-06
```

`check` runs the same full validation and bundle-size checks as resolution. It prints only action and change counts plus a limitation notice; it does not print records, IDs, rationale, paths or hashes. The candidate cutoff is required and must be on or after the preparation cutoff. Review/access dates must satisfy existing dataset rules at that candidate cutoff; unknown dates remain unknown. Policy target dates retain the existing schema semantics.

Create one complete private resolution bundle:

```sh
python3 -m scripts.resolution resolve \
  --source private-output/fictional-source.json \
  --packet private-output/fictional-packet.json --as-of 2024-01-06 \
  --output private-output/fictional-resolution.json
```

There are no add, rename, merge, partial-record-patch or automatic-approval actions. Unsupported actions and unknown fields are rejected. Records outside the prepared selection remain byte-equivalent in canonical JSON. To work against a changed catalog or a different selection context, prepare a fresh packet and deliberately transfer any still-applicable proposals; the tool does not rebase decisions automatically.

## Inspect and export the candidate

The `catalog_resolution` bundle is one JSON artifact containing:

- The full prepared context, complete selected original records, queue reasons, supplied decisions and rationale.
- A standard maintenance comparison embedding both complete source and candidate snapshots, including records outside the selection.
- Every field change, separate policy-stage and evidence-status transition flags, and the candidate's recomputed structural queue.
- Deterministic action counts, each decision's before/after record hashes, a decisions hash and a full resolution hash.

A decision count measures supplied actions. A change count measures actual resulting record changes. Keeping a queued record does not clear the queue; an identical replacement increments `replace` while remaining unchanged. The candidate queue is evaluated at the candidate cutoff, so elapsed calendar days can add structural stale reasons even when every record is kept.

Export one fresh artifact per command. Each export first reconstructs the complete expected resolution and compares all fields, not just its outer hash:

```sh
python3 -m scripts.resolution export private-output/fictional-resolution.json \
  --kind snapshot --output private-output/fictional-candidate-snapshot.json

python3 -m scripts.resolution export private-output/fictional-resolution.json \
  --kind dataset --output private-output/fictional-candidate-records.json

python3 -m scripts.resolution export private-output/fictional-resolution.json \
  --kind comparison --output private-output/fictional-comparison.json

python3 -m scripts.maintenance report private-output/fictional-comparison.json \
  --output private-output/fictional-comparison.html
```

The candidate snapshot can enter later maintenance/review cycles. The dataset is an ordinary full schema collection, not an approval document. The comparison opens in the existing offline HTML viewer with complete before/after evidence. Decision rationale remains in the resolution JSON; it is not injected into source records or the comparison viewer. Review both artifacts when rationale matters.

An empty source or an empty queue is valid and produces a no-op proposal when no decisions are required. Removing every selected record can produce an empty candidate snapshot and comparison. Empty `dataset` export is refused because the existing standalone dataset schema requires at least one record. Export a snapshot for that case; the schema is unchanged.

## Export a reduced-content structural summary

When a review-progress record does not need full evidence, export a summary to a new private file:

```sh
python3 -m scripts.resolution export private-output/fictional-resolution.json \
  --kind summary --output private-output/fictional-resolution-summary.json
```

This command still reconstructs and verifies the **entire resolution bundle first**, including fields that the summary will omit. A stale or altered rationale, record, queue or aggregate cannot bypass validation by choosing a smaller export. The original input and 32 MiB artifact limits still apply.

The summary has `artifact_type: catalog_resolution_summary` and policy `catalog_resolution_summary_v1`. Its output schema is a fixed projection containing only structural counts, one cutoff-change boolean and fixed explanatory text:

| Field | Meaning |
|---|---|
| `record_counts`, `record_types` | Before/after totals and counts of the stored real/synthetic labels; these do not authenticate records. |
| `decision_counts` | Supplied keep/remove/replace actions and untouched records. |
| `change_counts` | Actual added/removed/changed/unchanged records; an identical replacement is unchanged. |
| `transition_counts` | Counts of policy-stage and verification-status changes among IDs present in both snapshots. Removed records do not count as transitions. |
| `review_queue` | Preparation and candidate queued-record totals plus counts for each fixed structural reason code. Reason counts can overlap and source-level reasons can occur more than once per record. |
| `queue_cutoff_changed` | Whether the preparation queue and candidate queue use different cutoffs. This compares the two queue contexts, not the source snapshot's validation date. |

No record IDs, hashes, rationale, names, claims, URLs, file paths, dates, dynamic field paths or other supplied text are copied. Calendar dates and configured age limits are intentionally omitted. A changed queue cutoff can introduce stale reasons without any record edit; fewer reasons do not prove better evidence or completed human review. Keeping a queued record leaves its structural reasons intact.

**Reduced content is not anonymization.** Counts can still identify small or known collections, and this artifact is not automatically safe to publish. The same private writer and no-overwrite rules apply. Keep the full resolution privately when detailed evidence or reproducibility matters. Different original records can intentionally produce identical summaries: the summary contains no source identity, cannot authenticate its origin and cannot be imported as a resolution, snapshot or dataset. It supports reviewing counts, not approving evidence or certifying that a human reviewed it.

## Content binding and trust boundary

The immutable `basis` contains the exact source snapshot and dataset hashes, scope, complete fixed queue context, sorted targets, original record hashes and full selected before records. Its hash covers that entire basis. Check/resolve reverify the separately supplied source snapshot and recreate the expected basis. Altered records, stale source/cutoff hashes, omitted targets, changed reasons or forged summary counts are rejected even if someone recomputes the basis hash. Missing, duplicate, unknown or unselected decision IDs are rejected. Input decision order is normalized by ID for deterministic results.

The decision fields are intentionally editable. Their edits cannot be distinguished from an authorized person's edits: **hashes are consistency checks, not signatures, identities or proof of review**. Changing all inputs and recomputing every hash can create a different internally consistent proposal. No old private artifact or remote source is consulted to establish authenticity. Final-bundle verification catches changed decisions, candidate records or summaries that do not match full recomputation; it cannot authenticate the author of a coherently regenerated bundle. Protect original source snapshots and review the actual proposed evidence.

Queue reasons and their disappearance are structural signals only. An empty queue does not establish evidence truth. Source URLs remain stored text and are never fetched. No existing public dataset or repository file is updated by these commands.

## Privacy, output guarantees and limits

All default outputs are under ignored `private-output/`. The bundle and exported comparisons contain complete source/candidate catalogs, including unselected records. Rationale is arbitrary private text. These artifacts are **not redacted**; examine them before sharing. Terminal diagnostics contain fixed messages and bounded counts, not supplied values or file locations.

Each write uses the existing private writer: fresh files only, POSIX `0600` file permissions, `0700` for newly created directories, held directory descriptors, no-follow traversal, an exclusive temporary file and atomic no-clobber publication. Existing output files, source files, hard links, symlink targets/directories and parent traversal are refused. All input validation and encoding finish before output directories are created. `check` writes nothing. Each prepare/resolve/export operation writes one artifact, so a failed later export cannot leave a partially updated group of candidate files.

A filesystem cleanup failure or interruption after publication can leave a complete output even when the command fails. Existing data is never replaced. Inspect the destination and choose a fresh name before retrying. Use real output directory paths: an output path through a symlink is intentionally rejected. These guarantees require the existing supported POSIX filesystem facilities.

The existing 10000-record limit applies to catalogs and the decision list. Every imported or exported artifact is limited to 32 MiB; the full bundle can exceed the limit while each input fits because it preserves multiple full evidence views. Strict UTF-8 JSON rejects duplicate keys, nonfinite numbers and malformed nesting. No new runtime dependencies, database, network access, browser storage or telemetry are introduced.

Resolution inputs use the shared regular-file artifact loader. On POSIX systems, named pipes (including links to them) are rejected without waiting for a writer; directories and devices are rejected before payload reading. Links to regular input JSON files remain supported for reading. The existing no-link output rules are unchanged, and these input checks do not impose a deadline on arbitrary filesystem I/O.

Exit codes: `0` for success, `1` for input/validation/output failure, `2` for invalid arguments, `130` for an interrupted operation. A successful command establishes structural consistency only.
