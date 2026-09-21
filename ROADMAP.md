# Roadmap

The first data format and local validation tools are implemented. The first **3 real records have received AI agent review against official sources; 0 have completed human review**. There are also 2 pending leads and 1 synthetic example. Agent-reviewed records require independent human review before counting toward the phase-one target of 10 human-reviewed records. An offline CLI index and self-contained HTML explorer with filtering, facets and schema exports are implemented.

## PR 1: Policy-record format and review rules

- [x] Define country or jurisdiction, policy title, original sources, publication date and last-review date.
- [x] Distinguish announcement, proposal, adoption, entry into force and implementation, storing verification results independently.
- [x] Record precise claims, scope, change history and evidence gaps.
- [x] Provide JSON Schema, field documentation and a complete example clearly marked as fictional.

Acceptance: the format can express actual policy stages. Assigning stages to real records still requires evidence review; preparedness measures must not be treated as predictions of when war will occur.

## PR 2: First traceable records

- [x] Extract 3 source leads from the earlier README, all using pending status, unknown policy stage and empty review dates.
- [x] Create 3 independent records from original EU sources, complete agent source review and document the method.
- [ ] Obtain independent human review of these 3 records, then expand to 10.
- [x] Distinguish an EU non-legislative strategy, a plan to develop subsequent guidelines and actual programme deployments, without inferring member-state legal obligations.
- [ ] Split treaty-registry leads by country, and review reservist-age changes separately from population targets.
- [x] Retain evidence locations and correction history for the first records; keep unreviewed leads pending.
- [ ] Check subsequent publication of the 72-hour guidelines and update from original evidence rather than inferring completion from a target year.

Acceptance: 10 real policy records have been reviewed by humans and can be checked independently. Each has sources supporting its specific claim, dates and review notes. Previous AI answers and synthetic examples cannot substitute for evidence.

## PR 3: Reproducible data checks and presentation

- [x] Use the Python standard library to check required fields, duplicate IDs across files, real calendar dates, evidence locations and consistency of review dates.
- [x] Cover reviewed proposals, pending leads, missing evidence, invalid dates, synthetic-source misuse and CLI input errors with regression tests.
- [x] Produce an offline CLI index filterable by jurisdiction, topic, policy stage and evidence review status, with date filters, facets and schema exports.
- [x] Generate a self-contained offline HTML explorer with evidence details, fixed-cutoff filters and filtered JSON downloads.
- [ ] Consider a hosted website once the data and review process are stable.

Acceptance: others can validate the same data using the README commands. The offline CLI index is reproducible and preserves each conclusion's evidence and applicable period. Passing automated checks establishes only compliance with structural rules.
