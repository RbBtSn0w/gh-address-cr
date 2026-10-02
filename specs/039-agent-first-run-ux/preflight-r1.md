# Architecture Preflight: Spec 039 R1 (needs-action outcomes counted separately)

Trigger: reshapes the telemetry reporting contract (AGENTS.md blast-radius list).
Decision input: Q2 resolved by the maintainer as "separate counter". Fixes the
3.16.0 regression F4 / issue #307.

| Item | Answer |
|---|---|
| Authoritative state owner | Unchanged. Session telemetry (`telemetry.jsonl`, one row per bound command) stays the source for the efficiency report; the report remains advisory and never changes the gate verdict or exit code. |
| External facts / event inputs | The command's exit code (as before) plus the `reason_code` that command emitted, captured in-process through a context variable that is reset at command start (`cli.main`), set where the outcome is decided (`high_level._emit_native_summary`, the single and stack final-gate handlers), and read once by `_record_command_metric`. Same lifecycle as the existing persistence totals; nothing is read back from artifacts. |
| Projection shape | `ExecutionMetric.outcome` (`success` / `needs_action` / `timeout` / `failure`), persisted as an additive `outcome` field. Runtime events map `needs_action` to event status `needs_action`. The efficiency report gains `needs_action_count`; `success_rate` excludes `needs_action` (and `unknown`) from its denominator. Rows written before this change have no `outcome` and keep their exit-code meaning. |
| Decision function | `telemetry_runtime.classify_command_outcome(exit_code, reason_code)`: 0 → success, 124 → timeout, 5 with a reason in `NEEDS_ACTION_REASON_CODES` → needs_action, everything else → failure. The allowlist holds the high-level inspection blocks (`WAITING_FOR_SIMPLE_ADDRESS`, `BLOCKING_ITEMS_REMAIN`, `WAITING_FOR_FIX`, `AUTO_SIMPLE_NOT_ELIGIBLE`) and the final-gate verdict codes. Exit 5 is also used for session errors, invalid input, GitHub failures and rejected agent commands; those are not listed and stay failures. A stack gate blocked by a member uses the member's gate reason (`StackGateResult.blocking_reason_code`). |
| Retry semantics | `is_retry` now requires the previous run of the same command to be a failure; rerunning `address` after a needs-action block is the documented loop. |
| Side-effect plan | None. No GitHub or session writes added. |
| Artifact truth / self-reference | A final-gate report is built before that final-gate's own metric is recorded, so a command never classifies itself. OTel spans are unchanged: `process.exit.code` stays the honest exit code (README already states Status-to-Action exits are not errors). |
| Contract docs | `README.md` completion section and `skill/references/completion-contract.md` define `needs_action_count`. `SAFE_STATUSES` for imported host events is unchanged; `needs_action` is produced only by runtime events. |
| Recovery / replay | Historical rows replay with their old meaning; new rows carry `outcome`. Unknown `outcome` values read back as absent. |
| Executable contract tests | `tests/core/test_command_outcome.py` (policy table, stack reason, retry, persistence round trip); journey invariant I2 in `tests/contract/test_agent_journey_contract.py` (documented path reports 100% with `needs_action_count >= 1`; status checks and a premature final-gate before the fix are needs-action, verified RED at 90.9% on the previous code). |

Reduces ambiguity: one function now owns what a non-zero exit means for telemetry, instead of every exit 5 being read as a failure.
