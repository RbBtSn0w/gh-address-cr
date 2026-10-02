# Architecture Preflight: required checks with zero check runs (Spec 039 Q1)

Trigger: changes `final-gate` truth output (AGENTS.md blast-radius list). Maintainer decision Q1:
block explicitly with a verdict code.

## Verified behavior (gh 2.101.0, 2026-10-02)

- `gh pr checks <pr> --json ...` on a PR with no check runs: exit 1, empty stdout,
  `no checks reported on the '<branch>' branch` (ACT-02, #318).
- `gh pr checks <pr> --json ... --required` when the base branch has no required status checks
  (RbBtSn0w/gh-address-cr#322, base `main`): exit 1, empty stdout,
  `no required checks reported on the '<branch>' branch`. #318's matcher did not recognize this
  wording, so `--require-required-checks` failed as `GITHUB_API_FAILED` / "failed to evaluate".

| Item | Answer |
|---|---|
| Authoritative state owner | Unchanged: the gate evaluates fresh GitHub facts; nothing is persisted beyond the existing metrics. |
| External facts | `gh pr checks` (with `--required` for `--require-required-checks`). Both "no checks" wordings map to `no_checks` in `github/pr_checks.pr_checks_result`. |
| Projection | New count `pr_checks_missing_count` = 1 when a checks requirement is set and zero check rows exist. Additive machine field (appears in `counts` and Machine Gate Diagnostics). |
| Decision function | `FAILURE_ORDER` gains `FINAL_GATE_REQUIRED_CHECKS_MISSING` after `FINAL_GATE_PR_CHECKS_NOT_GREEN` (waiting_on `checks`). `Gatekeeper.run` treats `GitHubNoChecksError` as zero rows, so the verdict comes from the same table as every other gate failure. |
| Verdict change | Before: blocked as an evaluation error (exit 5, stderr "Final gate failed to evaluate"). After: blocked with a verdict (exit 5, `reason_code=FINAL_GATE_REQUIRED_CHECKS_MISSING`, `Next action:` naming the flags). Still blocked; no new pass path. |
| Telemetry | Added to the needs-action allowlist (`telemetry_runtime.NEEDS_ACTION_REASON_CODES`). |
| Side effects | None. |
| Contract docs | `skill/references/completion-contract.md`, `skill/references/status-action-map.md`. |
| Tests | `tests/core/test_pr_checks.py` (required wording), `tests/core/test_command_outcome.py` (allowlist), `tests/contract/test_agent_journey_contract.py::RequiredChecksMissingContractTests` (both flags, verdict, count, next action), `tests/test_final_gate.py` counts contract updated for the additive key. |
