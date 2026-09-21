# Policy records v1: Fields and evidence review rules

The machine-readable structure is in [`schema/policy-records.schema.json`](../schema/policy-records.schema.json). The standard-library CLI is the repository's validation entry point. It additionally checks real calendar dates, unique IDs across files, source URLs and the relationship between review and source-access dates. JSON Schema validators generally need `format` checking enabled separately and cannot replace cross-file or factual review.

Each JSON file has only `schema_version: 1` and a nonempty `records` array at the top level. Records reject extra fields. UTF-8 JSON must not contain duplicate keys or NaN/Infinity. `null` means unknown or not yet occurred; do not substitute empty strings, zero dates or guessed dates.

`schema_version` must be the integer `1`. The CLI rejects the string `"1"`, the float `1.0` and the Boolean `true`.
Fields that allow `null` must still retain their keys. An unknown value and a missing field are different conditions. JSON null is written as unquoted `null`; the string `"null"` is neither a valid date nor a null value.
Enum values are case-sensitive. For example, use `verified`, not `Verified` or a translated label.

When only a year or month is known for a policy or publication date, retain `null` and describe the known precision in a note. Do not invent the first day of that year or month.

An `id` starts with a lowercase ASCII letter and contains only lowercase letters, digits and single separating hyphens. Underscores, spaces, trailing hyphens and consecutive hyphens are not allowed.

| Field | Meaning and rules |
|---|---|
| `id` | A lowercase English slug unique across all input files. Synthetic records use the `synthetic-` prefix; real research records must not use it. |
| `record_type` | `real` is a research record about an actual policy, possibly still pending review; `synthetic` is an entirely fictional format example. |
| `jurisdiction` | Country, EU or treaty-registry scope. Do not automatically turn an EU recommendation into member-state law. |
| `topic` | `reserve_service`, `treaty_status`, `civil_protection`, `household_preparedness`, `emergency_stockpiles` or `other`. |
| `title` / `claim` | A title and one precise, independently verifiable statement. Pending leads may state a specific research question; complete real records must focus on a single claim. |
| `scope` | Applicable population, country, period or measurement definition. Do not include personal names, household addresses or account information. |
| `policy_stage` | The policy's stage, described below. |
| `verification_status` | The review result for the current claim, described below. |
| `dates` | Always contains `announced_at`, `adopted_at`, `effective_at` and `target_at`, each as `YYYY-MM-DD` or `null`. Target dates may be in the future. |
| `sources` | At least one source, using the fields in the next section. |
| `last_verified_at` | Date of the latest evidence review. Must be `null` for `pending`; other verification results require a valid date that is not in the future. |
| `verification_note` | Current review method, conclusion and limits. Passing format checks must not be described as human verification. |
| `limitations` | A nonempty array of nonblank strings explaining evidence limits. |
| `change_history` | At least one `{ "date": "YYYY-MM-DD", "summary": "..." }` entry. Record corrections and significant status changes, without contributors' private information. |

The CLI neither validates nor changes the order of `change_history`. Preserve a readable correction timeline when editing it.

## The two statuses are independent

| Policy stage | Meaning |
|---|---|
| `unknown` | Evidence is insufficient to determine the stage. |
| `announced` | An intention has been announced; this does not establish that a formal proposal exists. |
| `proposed` | An identifiable proposal or draft exists. |
| `adopted` | The relevant adoption process has been completed; this does not automatically mean entry into force. |
| `in_force` | Clear evidence establishes that the measure has entered into force. |
| `implementing` | Evidence shows actual implementation is underway. |
| `completed` | Completion of the specific action described in the record has been established. |
| `withdrawn` | The recorded proposal or measure has been withdrawn. Treaty withdrawal requires a precise claim and legal timeline; this label alone cannot replace them. |

| Verification result | Meaning |
|---|---|
| `pending` | Evidence review has not been completed. |
| `verified` | Review of original evidence supports the current precise statement. Record the reviewer type and limits in `verification_note`. |
| `disputed` | Reviewed evidence conflicts with the current claim; explain the conflict. |
| `outdated` | The record or evidence has been shown to no longer reflect the current position; specify the applicable period. |
| `inconclusive` | Review was attempted, but the evidence does not support a definite conclusion. |

For example, `proposed + verified` means that the proposal's existence is verified, not that it has been adopted. `unknown + verified` may also describe a verified fact whose policy cannot yet be assigned to a later stage. Statuses do not advance automatically.

The CLI does not compare announcement, adoption, effective and target dates chronologically. Review the timeline against original sources.

`verified` does not mean government endorsement, independent audit or human certification. Both human and AI-agent source reviews must state their review method. Agent review must not be described as human confirmation. The phase-one human-review acceptance requirement remains in place.

New leads whose sources have not been read use `policy_stage: "unknown"`, `verification_status: "pending"` and `last_verified_at: null`. This is an editorial rule; the CLI does not infer policy stage from verification status. An inaccessible link does not automatically justify `disputed` or establish that a policy is false.

## Source fields

Every source has these fields:

- `url`: An original HTTPS source link without user information, passwords, obvious credential query fields, whitespace or nonstandard ports. Localhost, local domains and IP address literals are prohibited. Host classification uses Python's standard-library IDNA normalization, requires valid DNS-label syntax and removes one trailing DNS dot. Percent-escaped hostnames, bracketed authorities and numeric address forms, including shortened, hexadecimal and octal IPv4 spellings, are rejected. This prevents compatible Unicode spellings from bypassing local-address or reserved-domain restrictions. Source-domain counts use the same normalized host while preserving every stored URL. These structural rules do not resolve DNS or claim equivalence with every browser's Unicode-domain processing. Ordinary query parameters on official sources may remain. Prefer public government, parliamentary, legal-database and international-organization pages. Manually remove private share codes, tokens, login links and tracking parameters; the CLI cannot recognize all private information.
- `publisher` / `title`: Publishing organization and document title. An unreviewed lead must clearly identify its title as a lead label.
- `published_at`: Original publication date, or `null` if unknown. Do not substitute the access date.
  The CLI does not compare publication and access dates chronologically. Investigate page versions and date meanings when they appear inconsistent.
- `locator`: Provision number, page, section or a stable paragraph location; `null` if not found.
- `accessed_at`: Actual access date, or `null` if not visited. It must not be in the future or later than the record's last-review date.
- `supports`: An original summary of exactly what the cited location supports and what it does not establish; `null` if unread. Avoid copying entire copyrighted passages.

For `verified` records, every source must have complete `locator`, `accessed_at` and `supports` fields. Unreviewed further-reading leads belong in separate `pending` records. Other verification results may retain missing evidence locations to describe genuine verification difficulties, but still require a review date and explanation.

URL validation is not an allowlist of official institutions. Passing HTTPS syntax and domain checks does not establish publisher credibility or evidence quality.
The CLI never deduplicates source entries. Repeated exact URLs are accepted by default; `--unique-sources` rejects them on request. Remove duplicate citations during review rather than counting them as independent evidence.

## Synthetic examples, real data and checks

`examples/synthetic.json` contains 1 fictional example. It uses `verified` to demonstrate complete fields; its access date, review date, organization and supporting statements are invented. Sources may use only `example.org` or `example.invalid`. It does not count toward real records or verified policies. `data/verified.json` contains 3 real records with agent source review; see the [source review log](source-review.md) for method and scope. `data/pending.json` retains 2 research leads from the earlier README, including a treaty index that still needs country-specific records. Pending leads, synthetic examples and records without human review do not count toward the phase-one target of 10 human-reviewed policy records.

Normalized synthetic-source hostnames must exactly match the allowlist. Subdomains such as `sub.example.org` are not allowed.
Real-record sources must not use `example.com`, `example.net`, `example.org`, their subdomains or domains ending in `.example` or `.invalid`.

```sh
python3 scripts/validate_records.py data/verified.json data/pending.json examples/synthetic.json
python3 -m unittest discover -s tests -v
```

Python 3.10 or later is required. Only the standard library is used; the CLI does not access the network, install dependencies or fetch sources. Exit code `0` means structural checks passed, `1` means a file or record error, and `2` means a command usage error. Diagnostics use input numbers such as `input-1` and `input-2`, field locations and rules, without printing paths, filenames or raw field values.

For factual verification, read original evidence and retain stable locations, then write precise claims, scope, dates, limitations and correction history. Run validation and submit a PR for human review. A complete JSON file that passes validation can still contain incorrect facts; machine checks cannot replace human judgment.
