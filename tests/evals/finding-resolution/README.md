# Finding-resolution eval

Five real review findings from this repository's own PRs. Each one is replayed
against a hermetic PR fixture, so the same input can run repeatedly. The eval
answers one question before any new layer is added: does the same input always
end in a legal state, an effective fix, and consistent verification evidence?

| Sample | Axis | Source thread | Real handling |
|---|---|---|---|
| `nonfinite-shutdown-wait` | baseline | #351 `telemetry_shutdown.py` (CodeRabbit) | fix |
| `malformed-report-fields` | lease (two threads, one file) | #327 `compare_telemetry_by_runtime.py` (Copilot) | fix x2 |
| `preflight-timeout-claim` | classification (false positive) | #363 `cli.py` (Copilot) | decline, no code change |
| `stale-unused-parameter` | recovery (outdated at start, fixed by a later PR commit) | #324 `workflow.py` (Copilot) | fix |
| `windows-gh-matcher` | verification (a naive fix breaks an existing test) | #318 `pr_checks.py` (Copilot) | fix |

Each sample keeps the reviewer's comment verbatim in `threads/`. The one change
is that file paths are remapped to the fixture's `app/` package. The code is a
minimal, self-contained reconstruction of the pre-fix module.

## Layout

- `samples/<id>/sample.json`: the PR, its commits (`base/`, `head/`, `head-2/` overlays), threads, expected dispositions, and the reference solution.
- `samples/<id>/oracle.py`: a hidden test that is copied into the pushed PR head only at grading time.
- `fake_gh.py`: wraps `tests/fixtures/agent_journey/fake_gh.py`. The PR head follows the bare `origin`, so pushes reach the runtime, and every `gh` call is attributed to the runtime or the agent.

## Running

```bash
.venv/bin/python scripts/eval_finding_resolution.py run --agent scripted
.venv/bin/python scripts/eval_finding_resolution.py run --agent claude --model claude-sonnet-5-5 --repeats 5
```

- `--agent scripted` follows the reference solution. It must pass 5/5 and runs offline in `tests/test_finding_resolution_eval.py`.
- `--agent claude` launches headless Claude Code. It is configured as follows:
  - It runs with project settings only, so no user `CLAUDE.md`, plugins or MCP servers load.
  - The skill is installed from `skill/` into the fixture.
  - The runtime is the interpreter's `gh-address-cr`.
  - GitHub credentials are scrubbed and telemetry export is off.
  - Runs are serial.
  - Results go to `build/evals/finding-resolution/<run-id>/`: `summary.md`, `summary.json`, and per-run `run.json` and `transcript.jsonl`.

## Reading results

A run passes when all three criteria hold:

- **legal_state**:
  - `final-gate` passed;
  - every thread is resolved and replied to;
  - every reply is in the runtime evidence ledger;
  - the agent made no direct `gh` writes;
  - the fake modelled every runtime call.
- **effective_fix**:
  - dispositions match the sample;
  - the fixture's tests and the oracle pass on the pushed head.
- **consistent_evidence**:
  - every fix cites a commit in the PR and carries validation evidence;
  - runnable recorded validation commands pass on the pushed head.

The summary reports three evidence numbers:

- **Evidence consistency**: the gated criterion above. It counts runs.
- **Evidence rerunnability**: fixes whose recorded validation the grader could re-run. It counts fixes.
- **Verified remediation**: runs that passed and whose every fix's validation re-ran. Decline-only runs have no fix, so they are excluded.

A label-only record is visible in these numbers without being scored as a failed fix.

**Workflow deviations** lists each reason code off the documented path. For
every code it shows the runs where the code appeared, the step that hit it, the
step the agent ran next, and how many of those runs still passed. A code that
repeats across runs points at guidance or a state contract, not at a missing
recovery branch. `report` re-derives steps from each `transcript.jsonl`, so a
reporting change never needs a new agent run.

The **Rerunnable evidence** column is reported but does not gate a run. It counts
fixes whose recorded validation names a command the grader can re-run. A
`unittest X` entry counts as `python -m unittest X`. A label-only entry such as
`unit-tests=passed` is allowed by `SKILL.md`, but it cannot be re-verified.

`agent_gh_calls` lists every `gh` call that did not come from the runtime. That
includes reads made by the agent host itself, such as a PR lookup at startup.
Only writes fail a run.

Each `run.json` also records `runtime_observed`, which shows what the runtime
itself saw:

- `outdated_items`: the recovery sample must list its thread here.
- `lease_events`: the reference path records three per thread, even on item-scoped `agent resolve`.

An axis label is therefore backed by runtime state, not only by the sample's claim.

A k/5 result below 5/5 is the signal. Use `failed_checks` and the reason-code
table (grouped by lease, recovery, verification, classification and input) to
decide which layer to improve. Do not add an abstraction first.
