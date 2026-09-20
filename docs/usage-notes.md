# Validation CLI usage notes

The CLI only reads input files and reports validation results. It does not rewrite JSON or automatically correct records.

## Inputs and diagnostics

- Provide at least one JSON file; omitting files produces a command-line usage error.
- `-` does not mean standard input. Save the JSON to a file and pass its path.
- Directories are not recursively expanded into JSON files. Explicitly list every file to validate together.
- Do not pass the same file twice. IDs encountered on the second read also trigger duplicate detection across inputs.
- If one input cannot be read, the CLI still attempts to check later inputs. Any error makes the overall command fail.
- Success summaries go to standard output; data diagnostics go to standard error. Capture more than standard output when collecting failure details.
- `input-2.records[0]` means the first record in the second command-line input. Input numbers start at 1; array indexes start at 0.
- JSON syntax errors include line and column numbers. Duplicate keys, encoding failures and file-read errors use generic messages that omit raw values.
- Whether an access or review date is in the future is determined using the machine's current UTC date. Keep that boundary in mind when entering dates across time zones.
- The record count in a `PASS` summary includes real, pending and synthetic records from every input. It is not a count of verified policies.
