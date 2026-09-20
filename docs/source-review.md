# Initial official-source review log

Review date: September 20, 2026. An AI agent read the official pages and PDFs below, checking document identifiers, dates, sections and precise statements. Earlier chat answers were not used as evidence. No independent human certification, field investigation or delivery audit was performed. In `data/verified.json`, `verified` means the cited evidence supports the current precise claim. The number of completed human reviews remains 0.

## Three independent claims

| Record | Precise scope and status | Original evidence location |
|---|---|---|
| `eu-preparedness-union-strategy-adoption` | The non-legislative strategy was adopted on March 26, 2025; `adopted` applies only to that strategy document | [Commission implementation tracker](https://commission.europa.eu/priorities-2024-2029/security-and-defence/implementation-tracker_en), Non-legislative items → Adopted → entry for that date; cover of the [Joint Communication](https://commission.europa.eu/document/download/526806b6-c4e1-43d1-81b7-947308efbab1_en?filename=Joint+Communication.pdf), JOIN(2025) 130 final |
| `eu-population-self-sufficiency-guidelines-plan` | The 2025 document announced plans to propose guidelines for at least 72 hours of self-sufficiency; `announced` describes that development plan | The same Joint Communication, section 3, key action 14, printed page 10 (PDF page 11); [Action Plan annex](https://commission.europa.eu/document/download/755117bc-10ac-4549-a438-9767cf8f19d1_en?filename=Placeholder+Annex.pdf), printed page 3 (PDF page 4), row 28 |
| `eu-resceu-energy-generator-deployments` | The responsible authority reports that the energy reserve has deployed thousands of generators to Ukraine; `implementing` reflects evidence of existing deployments | [rescEU programme page](https://civil-protection-humanitarian-aid.ec.europa.eu/what/civil-protection/resceu_en), final paragraph of the Energy subsection |

## Date and interpretation limits

- The strategy communication and annex both have March 26, 2025 on their covers. The download list on the [Preparedness page](https://commission.europa.eu/topics/preparedness_en) labels them March 24 and 25 instead. The records use the document-cover dates and check the adoption date against the implementation tracker.
- The annex gives 2026 as an indicative year for developing guidelines, with no month or day. Because the current schema accepts only complete dates, `target_at` remains empty and the year is retained in the claim and source notes. A target year does not prove completion and must not be converted into December 31.
- The 72-hour record is limited to the plan in the 2025 source. This review did not systematically check later guideline publication, subsequent EU legislation or member-state rules. The historical record cannot establish a country's current household obligations.
- The rescEU footer showed a last update of August 11, 2026. The original publication and deployment dates were not specified, so `published_at` and policy dates remain empty. The page changes over time and provides no itemized delivery list. The thousands-of-generators statement is an official report, not an independent audit result. Hosting-country counts differed between sections of the page and were not used.
- Adopting a strategy, announcing guideline development and deploying equipment are distinct facts. None supports predicting when war will occur or claiming that every preparedness programme is complete.

## Lead migration and further review

The former `eu-household-preparedness-lead` was split into strategy-adoption and guideline-plan records. Its history remains in the guideline record's `change_history`. The Finland reservist-age and UN treaty-registry leads remain in `data/pending.json`; their sources were not visited and their verification status was not upgraded in this review.

The next reviewer can use the table to open each source and check the claim, locator, dates, policy stage and limitations, then record human-review results or corrections in a PR. Extending a claim to current implementation progress requires new official evidence and an updated applicable period, rather than a status-label change alone. The repository stores English summaries and public source links, without copying full pages or including private conversations, household records or account information.

Local structural checks cover all real data and synthetic examples, including unique IDs across files. Tests do not access the network or prove that policy claims are correct:

```sh
python3 scripts/validate_records.py data/verified.json data/pending.json examples/synthetic.json
python3 -m unittest discover -s tests -v
python3 scripts/privacy_check.py --history
```
