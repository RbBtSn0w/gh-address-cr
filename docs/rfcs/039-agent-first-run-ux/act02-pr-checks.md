> Archived design reference. Current code, tests, and `AGENTS.md` govern
> execution; historical delivery status and commands are not active instructions.

# Spec 039 addendum: ACT-02 — a PR with no check runs is a PR state

Source: postmortem of `RbBtSn0w/app-store-creative#8` on runtime 3.16.0 (action item ACT-02).

## Verified finding F9

- The archived PR #8 session telemetry records four `github.cli` exits of 1 at
  04:19-04:24 UTC; the branch's first CI run started at 04:59 UTC, so the PR had
  no check runs at the time.
- Real `gh pr checks --json` on such a PR exits 1 with empty stdout and
  `no checks reported on the '<branch>' branch` on stderr.
- `GitHubClient.list_pr_checks` accepted exit 1 only with a JSON payload, so it
  raised `GITHUB_API_FAILED`. The archived session's `check_summary` is
  `{"availability": "unavailable", "diagnostic_code": "GITHUB_API_FAILED"}`: the
  runtime, not only telemetry, reported a normal PR state as an API failure.
- Subprocess telemetry recorded every non-zero exit as a failure, including exit
  8 (checks pending). Present since before 3.16.0.
- The L1 fake `gh` returned `[]` with exit 0 for this case, which hid the defect.

## Fix

- `github/pr_checks.pr_checks_result(returncode, stdout, stderr)` is the one rule:
  `checks` (exit 0, or 1/8 with a JSON payload), `no_checks` (exit 1, empty stdout,
  "no checks reported"), otherwise `error`. Exit 1 with empty stdout is also how
  authentication and network failures look, so the stderr message decides.
- `list_pr_checks` raises `GitHubNoChecksError` (`GITHUB_PR_HAS_NO_CHECKS`), a
  `GitHubError` subclass. `address` / `threads` context reports
  `{"availability": "present", "counts": {}}`.
- `command_runner` records a `gh pr checks` probe with outcome `success` unless the
  rule says `error`. `ExecutionMetric.effective_outcome` unifies recorded and
  exit-code outcomes. OTel spans keep the honest exit code.

## Deliberately unchanged: final-gate

`final-gate --require-checks` on a PR with no check runs still blocks, as before
(any `GitHubError` fails gate evaluation), now with an accurate message. Returning
`[]` there would flip the gate to PASSED with zero checks, which changes final-gate
truth semantics. Open question for the maintainer: should "checks required, none
exist" be an explicit gate verdict (for example `FINAL_GATE_PR_CHECKS_NOT_GREEN`)?

## L1 rule: fakes mirror real tool exits

A journey fake must reproduce the real tool's exit code and stream shape for each
state it models. `tests/fixtures/agent_journey/fake_gh.py` now answers a PR without
checks the way real `gh` does, which turned journey invariant I2 RED until this fix.
