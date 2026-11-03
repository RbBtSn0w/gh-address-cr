# GitHub Actions navigation

| Workflow | Trigger and responsibility |
| --- | --- |
| Checks / Python | PR source changes, main pushes and weekly read-only product checks. Metadata edits run only the target guard. No preview artifact or publisher. |
| PR Commit Semantics | PR title/body edits and source updates. Lints intended squash metadata without checking out PR code. |
| Release | Friday 07:00 UTC and manual main dispatch. Repeats candidate checks, analyzes/builds read-only, hands immutable bytes to dependent publishers. Disabled unless `RELEASE_ENABLED == true`. |
| Homebrew | Explicit reusable call or manual same-version recovery with `version`, `source_sha`, `rebuild`. Retains four platform build/install verification before stable tap update. |
| Recover Plugin Marketplace | Manual version-only recovery of existing verified release assets. Shares the marketplace publication lock. |

Task PRs target main. No promotion, sync-back or PR preview workflows remain.
Existing remote workflow registrations and historical run evidence may remain;
remote cleanup and external timer shutdown require separate authorization.

Use `gh workflow run release.yml --ref main` for an immediate release after a
validated merge. This uses exactly the scheduled checks and does not select a
version or bypass the activation gate. See [Main release train](release/main-train.md)
for source/artifact boundaries, strict history lint, activation and partial recovery.
