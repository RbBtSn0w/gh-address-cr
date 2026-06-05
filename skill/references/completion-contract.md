# Completion Contract

`gh-address-cr final-gate` pass is mandatory before any completion statement. Add `--require-checks` or `--require-required-checks` when the PR workflow must also prove GitHub checks are green.

Never output "done", "all resolved", "completed", or equivalent unless:

- `gh-address-cr final-gate <owner/repo> <pr_number>` has just passed
- output includes `Verified: 0 Unresolved Threads found`
- output includes `Verified: 0 Pending Reviews found`
- unresolved GitHub threads = 0
- session blocking items = 0
- final-gate output includes a telemetry coverage label
- final response includes the exact `completion_summary_line` from `final-gate --machine` or the first bracketed line from `PR Completion Summary Guidance`

Final output must include:

1. the explicit `gh-address-cr final-gate <owner/repo> <pr_number>` command invocation used
2. `Verified: 0 Unresolved Threads found`
3. `Verified: 0 Pending Reviews found`
4. unresolved GitHub threads = 0
5. session blocking items = 0
6. the compact metrics line, for example `[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: runtime-only/medium (2 events, 100.0%; runtime only, no host import) | sources: runtime 2 | duration: no observed duration | slowest: none | issues: none]`
7. telemetry coverage label and efficiency report path
8. audit summary path + sha256

Use `completion_summary_line`, the structured `completion_summary` object, `PR Completion Summary Guidance`, `audit_summary.md`, or the machine-readable count lines printed by `final-gate` when run-scoped diagnostics are needed. The compact line carries telemetry coverage, confidence, source scope, observed duration, slowest operation, and issue summary.

Telemetry coverage labels are `complete`, `partial`, `runtime-only`, or `unavailable`. `runtime-only` is valid when host telemetry was not imported. `unavailable` must be reported explicitly instead of silently omitting metrics.

If final-gate reports abnormal coverage, diagnostics, success-rate drops, or inefficiency flags, briefly explain the user impact in the final response. These telemetry conditions are observed workflow evidence and do not become review-resolution blockers by themselves.

Final-gate machine output may include `logic_validation_signals`. Signals with `gate_effect=blocking` are completion blockers and must be fixed or explained through runtime evidence before claiming completion. Signals with `gate_effect=advisory` are non-blocking diagnostics; mention their implication when relevant, but do not treat them as a second review producer or as permission to bypass evidence, publish, or final-gate.

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
