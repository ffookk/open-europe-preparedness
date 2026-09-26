# Open Europe Preparedness

An open database project about European security and civil preparedness.

This project aims to organize public defence, civil protection and emergency preparedness policies from European countries and the EU. It helps readers distinguish online claims, original evidence, legal status, implementation progress and long-term targets, with a contribution process for continuing corrections through pull requests.

## Current status

The first policy-record JSON Schema, [field and evidence review rules](docs/record-format.md), Python standard-library validation CLI and regression tests are implemented. Policy stages and verification results are stored separately. Checks cover dates, unique IDs across files, evidence locators and required fields for reviewed records.

**The current dataset contains 3 real records reviewed against original sources by an AI agent, 2 pending source leads and 1 synthetic format example.** On September 20, 2026, the agent read official EU sources covering adoption of a non-legislative strategy, a plan to develop 72-hour self-sufficiency guidelines and an official statement about existing rescEU energy-reserve deployments. `verified` means that the evidence supports the precise claim; **these 3 records have not received independent human review and do not constitute human certification**. The [source review log](docs/source-review.md) records the method, evidence locations and limits. An offline catalog query engine, a self-contained HTML explorer and a reproducible snapshot/change-review maintenance workflow are implemented; a hosted website is not available. The synthetic example uses `verified` only to demonstrate complete fields.

## Run locally

Python 3.10 or later is required, with no third-party dependencies. Run these commands from the repository root; they do not access the network:

```sh
python3 scripts/validate_records.py data/verified.json data/pending.json examples/synthetic.json
python3 -m unittest discover -s tests -v
```

Development CI also runs a [portable offline browser regression suite](docs/browser-regressions.md) in Chromium and Firefox. Its pinned Node.js tools are optional development dependencies; the catalog runtime still uses only Python's standard library. Browser regressions use fictional records and do not establish factual or human review.

The CLI accepts one or more JSON files and checks for duplicate IDs across all inputs. Run `python3 scripts/validate_records.py --help` for argument help. Exit code `0` means success (help displayed or structural checks passed), `1` means a data or file error, and `2` means a command-line argument error. **Passing checks does not establish that policy facts are verified.** Factual verification still requires reading original sources, locating evidence and obtaining human PR review.

For repeatable date checks, add `--as-of YYYY-MM-DD` to set one inclusive ceiling for all review and source-access dates. Without it, the command uses the current UTC date. See the [cutoff example and limits](docs/usage-notes.md#reproduce-a-date-cutoff).

| Content | Location |
|---|---|
| Machine-readable data structure | [`schema/policy-records.schema.json`](schema/policy-records.schema.json) |
| Field, status and evidence review rules | [`docs/record-format.md`](docs/record-format.md) |
| 3 real records with agent source review | [`data/verified.json`](data/verified.json) |
| Evidence locations, method and review limits | [`docs/source-review.md`](docs/source-review.md) |
| 2 pending research leads | [`data/pending.json`](data/pending.json) |
| 1 entirely fictional complete example | [`examples/synthetic.json`](examples/synthetic.json) |
| Standard-library validation command | [`scripts/validate_records.py`](scripts/validate_records.py) |
| CLI usage details | [CLI usage notes](docs/usage-notes.md) |

## Query the offline catalog

The catalog validates all inputs together before returning any records. It supports combined filters, inclusive date ranges, reproducible review-age checks, deterministic sorting, pagination and counts by category. Every result retains the original sources, limitations and review notes. Results contain selected record text; inspect inputs before sharing or redirecting output.

```sh
python3 -m scripts.catalog query data/verified.json data/pending.json --as-of 2026-09-20 --topic household_preparedness --sort title
python3 -m scripts.catalog query data/verified.json --as-of 2026-09-20 --max-review-age 0 --dataset
```

Read the [catalog guide](docs/catalog.md) for filter semantics, schema exports and limits. This tool performs no source research and cannot promote a proposal into law or an agent review into human certification.

## Open the offline explorer

```sh
python3 -m scripts.catalog html data/verified.json data/pending.json examples/synthetic.json --as-of 2026-09-20
```

Open `private-output/policy-catalog.html` locally to search and filter records, inspect evidence and unknown dates, see category counts, print the current page, or download all filtered records as a schema dataset. The page uses no network resources, browser storage or telemetry. Its cutoff is fixed when generated. Source URLs are shown as text.

The generator creates a new file with private permissions, refuses existing destinations and symbolic links, and defaults to the ignored `private-output/` directory. Use `--output` with a new filename to generate another version. The HTML embeds full input records, even when the visible list is filtered; review it before sharing. Read the [offline explorer guide](docs/catalog.md#offline-html-explorer) for behavior and limits.

## Maintain snapshots and review proposed changes

Create content-bound catalog snapshots, compare full before/after records, and build a structural review queue using fixed review/source-access age limits. An offline maintenance report preserves original evidence, separates policy-stage and verification-status changes, and exports full artifacts or filtered review packets for human-reviewed corrections.

```sh
python3 -m scripts.maintenance snapshot data/verified.json data/pending.json --as-of 2026-09-20 --output private-output/catalog-before.json
python3 -m scripts.maintenance review private-output/catalog-before.json --as-of 2026-09-22 --output private-output/review-queue.json --html private-output/review-queue.html
```

Read the [complete maintenance workflow](docs/maintenance.md) for snapshot comparison, reason codes, offline reports and output limits. Hashes check consistency, not authenticity; removal means absence from a supplied snapshot, never repeal. No policy facts or review statuses are updated automatically.

For explicit corrections, the [offline resolution workflow](docs/resolution.md) prepares content-bound decision packets, validates keep/remove/replace proposals against a supplied source snapshot, and writes a separate candidate with complete before/after evidence. Unresolved decisions and stale source bindings are rejected. No original records or review statuses are changed automatically.

Its `export --kind summary` option revalidates the full resolution and creates a private structural-count summary without record text, identifiers, hashes or rationale. Counts remain potentially identifying; the summary does not authenticate its source or certify human review.


## Project goals

- Create structured records for independently verifiable policy claims.
- Record proposals, adoption, entry into force, implementation and completion separately.
- Build an index of official civil protection guides with attributed English summaries.
- Support source additions, status updates, factual corrections, translations into English and code contributions.

Initial topics include reserve and conscription systems, international treaty status, public defence and shelter policies, and household preparedness advice. Records should identify the relevant country, population, period and measurement definitions.

## Verification principles

Each record should address one independently verifiable question. For example, a change to the reservist age limit and a future target for the number of reservists belong in separate records.

**Policy stage and verification result must remain separate.** A proposal can be verified as existing while still awaiting adoption or entry into force; a population target is not a current count. Announcement, adoption, effective and target dates are not interchangeable.

Prefer governments, parliaments, legal databases, international organizations and official guides. Each record should provide source links, publishers, publication dates and relevant provisions, paragraphs or pages, explaining exactly what the evidence supports and its limits.

Unreviewed leads should remain pending with no last-review date. An inaccessible or broken link signals a need for follow-up; it does not establish that a policy is false. Automated checks validate only structure and consistency. Factual judgments still require human evidence review.

## Initial work and acceptance criteria

1. **Define the data format and status rules.** Provide the schema, field documentation and format examples, including representations for unknown dates, pending leads, policy stages and verification results.
2. **Review the first policy records.** Separate Finland's reservist-age question from its population target, build country-specific Ottawa Convention withdrawal timelines and check EU household preparedness advice.
3. **Establish contribution and validation workflows.** Add record checks and CI for required fields, dates and duplicate IDs while retaining human evidence review.
4. **Build a guide index.** Include official source links, language and version information, with clearly attributed summaries and scope.

Phase-one acceptance requires **10 independently verifiable policy records**, each with sources, policy stage, verification result, key dates, scope and last-review date. A first-time contributor should be able to follow the contribution guide to submit a correction PR. These records must meet the human-review requirement in the [roadmap](ROADMAP.md).

## Official source index and remaining leads

EU Preparedness and rescEU have received the limited agent source review described below; see the records linked above. Other links remain early research leads whose accessibility and policy claims have not been verified.

| Research area | Source lead | Follow-up focus |
|---|---|---|
| Finland's reserve system | [Finnish Government: reservist age limit](https://valtioneuvosto.fi/en/-/236553176/finland-to-raise-reservist-age-limit-to-65-years-as-of-2026) | Legal basis, affected population, effective date and definition of population targets |
| Anti-personnel mine treaty | [UN Treaty Collection](https://treaties.un.org/Pages/ViewDetails.aspx?chapter=26&clang=_en&mtdsg_no=XXVI-5&src=TREATY) | Country-specific notification dates, effective dates and declarations |
| EU preparedness | [European Commission: Preparedness](https://commission.europa.eu/topics/preparedness_en) | Strategy adoption and the 72-hour guideline plan reviewed; later guideline publication and national requirements remain pending |
| EU emergency reserves | [European Commission: rescEU](https://civil-protection-humanitarian-aid.ec.europa.eu/what/civil-protection/resceu_en) | Energy-reserve deployment statement reviewed; other capabilities and counts remain pending |
| Swedish civil protection guide | [Official handbook PDF](https://rib.msb.se/filer/pdf/30874.pdf) | Version, publication date and pages supporting summaries |

## Contribute

Read the [contribution guide](CONTRIBUTING.md) and [roadmap](ROADMAP.md), then propose a source lead or a change focused on one question. PRs should explain the change, its evidence and remaining uncertainty. Contributors can add sources, correct errors and translate source material into English without programming experience.

Third-party websites, publications and original documents remain subject to their own copyright and terms. Linking to them does not grant a new licence. Licensing for original project content is governed by the licence actually provided in this repository.
