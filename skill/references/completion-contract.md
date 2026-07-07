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

Only `gate_scope: "final"` output (from `gh-address-cr final-gate`) is completion proof. The `gate_scope: "inline"` summary emitted by `review`/`address`/`threads` is a pre-gate that does not evaluate pending reviews or PR checks; a `PASSED`/`PRELIM_PASSED` inline result is never sufficient to claim completion.

Final output must include:

1. the explicit `gh-address-cr final-gate <owner/repo> <pr_number>` command invocation used
2. `Verified: 0 Unresolved Threads found`
3. `Verified: 0 Pending Reviews found`
4. unresolved GitHub threads = 0
5. session blocking items = 0
6. the compact metrics line. Degraded (no timing, no host import) looks like `[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: runtime-only/medium (2 events, 100.0%; runtime only, no host import) | sources: runtime 2 | duration: no observed duration | slowest: none | issues: none]`. Activated (validation timing + host import) looks like `[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: partial/high (9 events, 100.0%; runtime+host import) | sources: runtime 2, assistant-host 7 | duration: 21.4s | slowest: unit-tests (4.2s) | issues: none]`. Prefer the activated shape by carrying `--validation cmd=passed@<n>ms` timing and importing host telemetry before the gate.
7. telemetry coverage label and efficiency report path
8. audit summary path + sha256

Use `completion_summary_line`, the structured `completion_summary` object, `PR Completion Summary Guidance`, `audit_summary.md`, or the machine-readable count lines printed by `final-gate` when run-scoped diagnostics are needed. The compact line carries telemetry coverage, confidence, source scope, observed duration, slowest operation, and issue summary.

Telemetry coverage labels are `complete`, `partial`, `runtime-only`, or `unavailable`. `runtime-only` is valid when host telemetry was not imported. `unavailable` must be reported explicitly instead of silently omitting metrics.

For local development loops, `runtime-only` is advisory rather than abnormal by itself. Report the label and its implication, but do not expand it into a blocker or mandatory exception narrative unless additional telemetry diagnostics, inefficiency flags, or gate blockers are also present.

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
