# Repeatable offline browser regressions

The committed browser suite generates fictional catalog and maintenance pages, runs them in Playwright's Chromium and Firefox engines, and validates their downloaded JSON with the Python catalog and maintenance verifiers. It uses the fixed cutoff `2024-01-05`; it does not read private inputs or fetch source websites.

From the repository root, with Python 3.10 or later and Node.js 24:

```sh
npm ci --ignore-scripts --no-audit --no-fund --prefix tools/browser
cd tools/browser
npx --no-install playwright install chromium firefox
npm test
```

Dependency and browser installation require network access. On a supported Linux host, use `playwright install --with-deps chromium firefox` to install browser system requirements too. The lockfile pins Playwright and its core to `1.63.0`; these are development tools only. The Python runtime remains standard-library-only. Set `PYTHON_BIN` to an alternate Python executable when necessary. `npm test -- chromium` or `npm test -- firefox` runs one engine for diagnosis; normal CI requires both.

The actual page checks run in isolated offline browser contexts, abort unexpected network routes, and fail on external request attempts, page exceptions or dialogs. They cover:

- Exact, distinct jurisdiction and publisher names containing spaces or underscores, including catalog facets.
- Combined search/category filters, a source-change filter, reset behavior and empty results.
- Review age at the fixed cutoff and an invalid date range that must disable export.
- Independent maintenance queue views and removed-only selections that cannot export current records.
- Exact filtered and complete record exports, preserving every original evidence field.
- Full report and snapshot downloads, rechecked through their recomputing Python verifiers; removed-record packets retain before evidence and an absent after record.
- Literal hostile record text, no active injected image, no browser storage, and a narrow viewport without horizontal overflow.

Generated fixtures and downloads use an isolated temporary directory that is removed on completion. Failures print a fixed scenario name without record content or machine paths. CI does not upload screenshots, downloads or separate artifact bundles. GitHub still retains its normal workflow logs.

CI runs the Python suite, privacy guard, English policy and documented dataset validation on Ubuntu with Python 3.10, 3.11, 3.12, 3.13 and 3.14, plus macOS with Python 3.14. A separate Ubuntu/Python 3.11/Node.js 24 job runs both browser engines. The existing required check named `validate` always runs and fails unless both prerequisite jobs succeed, including every matrix entry.

These checks demonstrate software behavior for fictional fixtures. They do not certify accessibility, physical printing, policy accuracy, source freshness or independent human review. They do not test Safari/WebKit or every browser version. The outstanding human evidence-review work remains open.
