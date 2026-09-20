# Privacy and contribution checks

## Measures in place

- Demonstrations and tests use fictional content; personal inputs and outputs belong in ignored local directories.
- Commits use a GitHub noreply email address. Check author and committer metadata before committing.
- CI has read-only repository permissions, receives no project secrets and does not upload inputs, outputs or test files as artifacts.
- GitHub Actions are pinned to specific commits and require review when updated.
- Privacy diagnostics show only rule names and file indexes, without echoing matched values.

## Run before submitting

```sh
git add <files-to-submit>
python3 scripts/privacy_check.py --history
python3 -m unittest discover -s tests -v
```

The check covers tracked working-tree text, staged content, text and filenames in reachable commits, and commit metadata. It detects common secret patterns, private conversation links, local user paths, non-example email addresses and sensitive directories. Binary files and symbolic links require manual handling.

This is a heuristic check. It cannot identify all personal information, custom credentials or image contents. It does not inspect untracked files, GitHub issue or PR bodies, unreachable remote history, platform-internal retention or existing external copies. Review diffs and collaboration content before publishing.

When sharing diagnostics, prefer input numbers, record indexes and rule names. Do not paste an entire unreviewed input file to provide context.

## If a problem is found

Stop submitting changes, then locate and remove the content locally. Do not paste raw values into issues, PRs, discussions, screenshots or logs. If credentials were exposed, revoke or rotate them before addressing repository history. Ordinary issues should record only remediation status without sensitive values.
