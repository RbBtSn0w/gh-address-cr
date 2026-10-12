# Spec 042: Telemetry overhead signal and budget calibration

Architecture Preflight for a change that touches the telemetry reporting contract
(`telemetry_overhead_budget_ms`, root-span attributes). Current code, tests, and
`AGENTS.md` govern execution. This is a static design reference, not an active-task
pointer.

## Problem (verified)

1. **The budget is smaller than the bound it is compared against.**
   Before this change, `TELEMETRY_OVERHEAD_BUDGET_MS = 250` (`core/telemetry.py`) while
   `SHUTDOWN_JOIN_TIMEOUT_SECONDS = 0.3` (then in `otel_tracing.py`, now in
   `core/telemetry_shutdown.py`). Spec 041 folds the
   previous invocation's exit wait into `telemetry_overhead_ms`, so one timed-out
   export (a 300 ms wait, build time ~0) already exceeds the budget. On a slow
   GitHub link this fires `TELEMETRY_OVERHEAD_EXCEEDED` without any telemetry work
   being abnormal. Production evidence (Honeycomb, 7 days): subprocess P95 ~2.5 s,
   `github.cli` P95 ~4.2 s, `agent.publish` P95 ~28 s.
2. **The diagnostic is invisible in Honeycomb.** `telemetry_overhead_ms` and
   `telemetry_shutdown_wait_ms` live only in `efficiency-report.json` and the
   `final-gate` summary. No span attribute carries them, so frequency cannot be
   measured fleet-wide.
3. **`gh_address_cr.command.reason_code` is not observable yet.**
   The span attribute only exists from v3.20.1 (earlier releases kept the code in a context
   variable for the outcome metric), and preflight failures set it on a child span instead of
   the root. Exit code 5 (~85% of non-zero exits) is therefore indistinguishable between
   "gate still has work" and "preflight failure" in Honeycomb (see Phase 0).

## Preflight

| Item | Decision |
| --- | --- |
| Authoritative state owner | None new. Review state stays in `runtime.sqlite3`. Telemetry stays observed evidence (Principle VIII). |
| External facts / inputs | The previous invocation's recorded exit wait (`telemetry-shutdown-wait.json`, Spec 041); the command's `reason_code`. |
| Projection | No new projection. The existing latest-wait record is read once at root-span start and exported as one numeric attribute. |
| Policy | One derived constant: `TELEMETRY_OVERHEAD_BUDGET_MS = round(SHUTDOWN_JOIN_TIMEOUT_SECONDS * 1000) + 200`. No branching, no per-cause special case. |
| Side-effect plan | No new IO beyond one extra best-effort read of an already-present local file at startup. No network change. |
| Artifact truth boundary | `efficiency-report.json` keys are unchanged; only the value of `telemetry_overhead_budget_ms` changes (250 -> 500). The new span attribute is a copy of the Spec 041 record, never read by `final-gate`. |
| Self-reference risk | The current invocation's own exit wait is still excluded (it happens after the span ends). The attribute reports the *previous* invocation's wait, linked by attribute only, never by span link or synthetic parent (cross-invocation stays correlation-first, Principle VIII). |
| Recovery / replay | Missing, stale, or malformed record yields no attribute and no diagnostic. Core flows stay fail-open. |
| Telemetry privacy | Numeric milliseconds only. No paths, no argv, no identifiers. |
| OTel layering | Attribute on the existing root span. No new child span, no promoted checkpoint. |

## Alternatives rejected

- **Per-cause suppression** (ignore the diagnostic when only the shutdown wait
  exceeded): adds a special-case branch on shared reporting code and keeps the
  budget inconsistent with its own input. The consistent budget removes the case.
- **Raise the budget to an unrelated constant (e.g. 1000 ms)**: hides real build
  slowness. Deriving it from the join bound keeps the two from drifting again.
- **Export `telemetry_overhead_ms` itself on the root span**: it is computed
  during `final-gate`/report build, which may run after or inside the span and
  would reintroduce the self-reference problem Spec 041 excluded.
- **Detached spool for undelivered spans**: still rejected for Spec 041's reason
  (new process lifecycle beyond the protected baseline, Principle X).

## Work breakdown

Default is independent PRs (no PR depends on another's API). Phase 0 gates only PR C.

### Phase 0: find why `reason_code` is not exported (investigation, no code)

1. Reproduce locally with an in-memory span exporter: run an exit-5 path
   (`final-gate` with a blocking reason) and assert whether the root span carries
   `gh_address_cr.command.reason_code`.
2. If absent locally: the defect is in-repo (call site runs under a non-recording or
   different current span; or the value fails `_REASON_CODE_PATTERN`). Proceed to PR C.
3. If present locally: the loss is downstream. Check the `otel-gateway` attribute
   allowlist (`RbBtSn0w/otel-gateway`). File an issue there; no code change here.

Exit criterion: a one-paragraph finding appended to this document.

**Phase 0 finding (reproduced with an in-memory exporter; gateway source checked).**

1. *Not released before v3.20.1.* Through v3.20.0, `note_command_reason_code` only set a
   context variable for the outcome metric; the span attribute was added in v3.20.1, which had
   3 root spans in the 7-day production window. The missing Honeycomb column is therefore
   expected, not evidence of a downstream drop. `RbBtSn0w/otel-gateway` (`src/index.ts`)
   filters by signal type only (`allowedSignals`), not by span attribute.
2. *In-repo gap, fixed in PR C.* Preflight failures (`review`, `address`, `threads`) run under
   the `gh_address_cr.cli.init` child span, so the attribute landed on that child and never on
   the root span; `output_preflight_error` also did not record the code. The code is now stored
   in the context variable and re-applied to the command-level span when the command finishes.

Expected after PR C ships: `gh_address_cr.command.reason_code` appears on exit-5 root spans of
the new version. Verify with a Honeycomb query grouped by that column.

### PR A: calibrate the budget (independent, smallest)

- Move `SHUTDOWN_JOIN_TIMEOUT_SECONDS` to `core/telemetry_shutdown.py` (already
  imported by both `otel_tracing.py` and `core/telemetry.py`; avoids a new import
  edge). Grep tests and docs for the old import path first.
- `core/telemetry.py`: derive `TELEMETRY_OVERHEAD_BUDGET_MS` from it (+200 ms margin).
- Tests (`tests/core/test_telemetry.py`):
  - update the three tests that rely on a 300/400 ms build against the old 250 ms
    budget (they pass a mocked `perf_counter`; raise the mocked build time above 500 ms);
  - update `test_efficiency_report_overhead_includes_previous_shutdown_wait` so the
    case that must exceed is wait 300 + build 250 (> 500);
  - add the regression for this spec: a timed-out wait of 300 ms with a fast build
    does **not** emit `TELEMETRY_OVERHEAD_EXCEEDED`;
  - assert the budget equals the derived value so the two cannot drift silently.
- Docs: README line ~218 and the RFC 041 note on the 250 ms budget.
- Compatibility: `telemetry_overhead_budget_ms` key and `TELEMETRY_OVERHEAD_EXCEEDED`
  reason code are unchanged; only the numeric budget changes. State this in the PR body.

### PR B: expose the previous exit wait on the root span (independent)

- Attribute name: `gh_address_cr.telemetry.previous_shutdown_wait_ms` (float, root span).
- Assemble it where the CLI entrypoint builds root attributes (`__main__.py`), using
  `read_last_shutdown_wait_ms()`; omit the attribute when it returns `None`.
- Tests (`tests/test_otel_telemetry.py`): attribute present with the recorded value;
  absent for missing, stale, and malformed records; presence never changes exit code.
- Also export `gh_address_cr.telemetry.previous_shutdown_timed_out` (bool) from the same record,
  omitted when the record carries no boolean. A single reader, `read_last_shutdown_record()`,
  validates the record once for both attributes.

### PR C: make `reason_code` observable (conditional on Phase 0)

- Fix the in-repo cause found in Phase 0, or skip if the loss is downstream.
- Contract test: for one needs-action path and one preflight-failure path, the root
  span carries `gh_address_cr.command.reason_code`, and the two values differ.

## Versioning decision

`gh_address_cr.command.reason_code` and the two `gh_address_cr.telemetry.previous_shutdown_*`
attributes are span telemetry, not part of the CLI's machine-readable stdout contract, so no
contract version bump is required. They are additive attributes on an existing span; consumers
that ignore unknown attributes are unaffected.

## `cr_metrics` `partial` review (task 4, read-only)

`completeness` is `partial` whenever any item is excluded (`cr_metrics.py`), so the label is
whole-report and coarse by design. On 50 local `cr-metrics.json` reports, 26 (52%) were
`partial`, matching the ~51% seen in production. Exclusion reasons over 122 items:

| Reason | Count | Reading |
| --- | --- | --- |
| `addressed_at_missing` | 65 | Items resolved without an accepted agent response (out-of-band). By design. |
| `verified_at_missing` | 65 | Same items. By design. |
| `verified_before_addressed` | 7 | Likely a real ordering defect, see below. |

For `github_thread` items, verification time is the `response_published` event, and the
publisher stamped it from a timestamp taken once at the start of `_publish_once`, before the
session load, the stack/login reads and the plan build. An acceptance that landed during that
window (slow GitHub reads, parallel agents) therefore got a publish stamp *earlier* than its own
`response_accepted`, and was excluded as `verified_before_addressed`. Evidence supports this:
all 7 local cases have a correct ledger order (`response_accepted` appended before
`response_published`) with timestamps inverted by 1 to 2 seconds, and a reproduction with a
1.7 s GitHub round trip showed publish events stamped at call start rather than when they
happened.

**Fixed in this change (PR D).** The publisher now stamps each plan when it executes, after the
session was loaded (an injected `now` still pins the stamp). The cr-metrics projection is
unchanged. Regression: `test_publish_events_are_stamped_after_the_acceptance_they_publish` fails
on the old behaviour (publish stamped 5 s before the acceptance window) and passes now. Reports
already written keep their old exclusions; they are rebuildable projections.

## Non-goals

- No change to `final-gate` truth semantics or exit-code meanings (5 stays 5).
- No new subsystem, spool, or sampling layer.
- No change to `cr_metrics` semantics; see the review section above.
- No Honeycomb trigger or board changes in this repository.

## Verification

Per `AGENTS.md`, from an activated `.venv` (worktree runs need `PYTHONPATH` pointing at
the worktree `src/`, otherwise the editable install silently tests `main`):

```bash
ruff check src tests scripts/build_plugin_payload.py
python3 scripts/check_mypy_ratchet.py
python3 -m unittest discover -s tests
python3 -m gh_address_cr --help
python3 -m gh_address_cr agent manifest
python3 scripts/build_plugin_payload.py --check
```

`src/` carries zero in-code lint suppressions; keep it that way.

## Success measures (post-release, Honeycomb `production/gh-address-cr`)

| Measure | Target |
| --- | --- |
| Local `TELEMETRY_OVERHEAD_EXCEEDED` caused solely by a 300 ms timed-out wait | 0 occurrences |
| Root spans with `previous_shutdown_wait_ms` (new versions) | > 0 within one release |
| Exit-5 root spans carrying `reason_code` (if PR C ships) | >= 95% of exit-5 spans on the new version |

## Open questions

- (Resolved in Phase 0) The `reason_code` gap was unreleased code plus a child-span placement bug, not the gateway.
- (Non-blocking) Is a 200 ms build margin right? Real build time is not exported
  today, so it is an engineering estimate; revisit with PR B data.
- (Non-blocking) Should `staging` receive traffic? It has no data, so it cannot
  validate releases.

## Executable contract tests

- `tests/core/test_telemetry.py`: derived budget, no false positive from a lone
  timed-out wait, true positive when build plus wait exceeds the budget.
- `tests/test_otel_telemetry.py`: root-span attribute presence/absence and fail-open.
- (PR C) root-span `reason_code` on needs-action versus preflight-failure paths.
