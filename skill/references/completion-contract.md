# Completion Contract

`gh-address-cr final-gate` pass is mandatory before any completion statement. Add `--require-checks` or `--require-required-checks` when the PR workflow must also prove GitHub checks are green.

Never output "done", "all resolved", "completed", or equivalent unless:

- `gh-address-cr final-gate <owner/repo> <pr_number>` has just passed
- output includes `Verified: 0 Unresolved Threads found`
- output includes `Verified: 0 Pending Reviews found`
- unresolved GitHub threads = 0
- session blocking items = 0
- final-gate output includes a telemetry coverage label

Final output must include:

1. the explicit `gh-address-cr final-gate <owner/repo> <pr_number>` command invocation used
2. `Verified: 0 Unresolved Threads found`
3. `Verified: 0 Pending Reviews found`
4. unresolved GitHub threads = 0
5. session blocking items = 0
6. telemetry coverage label and efficiency report path
7. audit summary path + sha256

Use `audit_summary.md` or the machine-readable count lines printed by `final-gate` when run-scoped diagnostics are needed.

Telemetry coverage labels are `complete`, `partial`, `runtime-only`, or `unavailable`. `runtime-only` is valid when host telemetry was not imported. `unavailable` must be reported explicitly instead of silently omitting metrics.

For run-scoped diagnostics that must keep artifacts available after the gate, use:

```text
gh-address-cr final-gate --no-auto-clean <owner/repo> <pr_number>
```

Successful `gh-address-cr final-gate --auto-clean ...` runs archive the PR workspace before deletion under `archive/<owner>__<repo>/pr-<pr>/<run_id>/`.

If gate fails, continue iteration; completion summary is forbidden.

## Why Review Comments Appear Later

- GitHub review bots run asynchronously.
- New commits trigger re-analysis and can generate new comments.
- Old threads can become outdated; new ones may appear on different lines.
