# Contribution guide

## Submit a clear, small change

1. Choose one independent issue from [ROADMAP.md](ROADMAP.md) and describe the expected result.
2. Make the change on a new branch and use a clear commit message.
3. Open a pull request explaining its purpose, sources, validation and limitations.

Use English for repository documentation, record descriptions, commit messages, issues, pull requests and discussions. Preserve exact source URLs, identifiers and necessary official names; summarize non-English source material in English.

## Evidence and data

- Prefer official documents, original datasets or original research for factual records, retaining precise evidence locations and review dates.
- Distinguish source statements, author inferences, unverified information and experimental results.
- State the applicable period for time-sensitive claims and retain necessary correction notes when updating them.
- Keep the existing `id` when correcting the same claim where possible; explain any split into separate claims in `change_history`.
- When a pending claim becomes `verified`, update its fields and move it to `data/verified.json`; do not keep a copy in both files.
- Do not treat a chat transcript or an AI answer itself as proof that a fact has been verified.
- Check licensing and redistribution conditions before importing external content; prefer links and the minimum necessary excerpts.

## Privacy and validation

- Use synthetic or legally public examples. Do not submit API keys, credentials, real household contact details or private conversations.
- Data changes should be traceable and reviewable. Code changes should include appropriate running instructions and observed validation results.
- Clearly label anything not implemented or verified; do not describe plans as completed work.

## Automated checks

Before submitting, read the [privacy check guide](docs/privacy.md), run the validation commands in the README and run `python3 scripts/privacy_check.py --history`. The PR Checks workflow runs privacy checks, unit tests and combined validation of real records, pending leads and synthetic examples.

After adding or changing an ID, validate all three data files together. Checking only the changed file cannot detect ID collisions with another file.

`main` currently requires PRs and a passing `validate` check, including for administrators. Commit on a working branch; force pushes and deletion of the main branch are prohibited. Automated checks do not replace review of facts, privacy or actual usability.

Run `python3 scripts/check_english.py` after staging changes. CI checks current tracked text, including decoded JSON values, for CJK scripts. This guard is not a general language classifier; manually review all public wording and GitHub collaboration text for English. Historical revisions are outside this check.
