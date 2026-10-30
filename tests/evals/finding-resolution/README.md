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

## Coverage

The axis labels name what each sample exercises, not the whole axis:

- **lease**: one agent handling two findings on one file, serially, through the lease lifecycle the runtime records. Concurrent claims, lease expiry, and crash-then-resume are not covered.
- **recovery**: a thread that is outdated at start and fixed by a later PR commit. Bot auto-resolve on push, publish interrupted midway, and threads going outdated after a push are not covered.

The fixtures are minimal reconstructions, so results are a small regression
baseline, not a production success rate, and not a comparison with an agent
that does not use `gh-address-cr`.

## Layout

- `samples/<id>/sample.json`: the PR, its commits (`base/`, `head/`, `head-2/` overlays), threads, expected dispositions, and the reference solution.
- `samples/<id>/oracle.py`: a hidden test that is copied into the pushed PR head only at grading time.
- `fake_gh.py`: wraps `tests/fixtures/agent_journey/fake_gh.py`. The PR head follows the bare `origin`, so pushes reach the runtime, and every `gh` call is attributed to the runtime or the agent.

## Running

```bash
.venv/bin/python scripts/eval_finding_resolution.py run --agent scripted
.venv/bin/python scripts/eval_finding_resolution.py run --agent external --runner runner.json --repeats 5 --keep
```

- `--agent scripted` follows the reference solution. It must pass 5/5 and runs offline in `tests/test_finding_resolution_eval.py`.
- `--agent external` executes the command explicitly configured in `runner.json`.
  The harness chooses no vendor, host, model, account, tool permissions or API budget.
- Both modes snapshot `skill/` once per eval and install it at `.eval/skill`
  inside each fixture. `skill_sha256` identifies the actual snapshot. The runtime
  is the interpreter's `gh-address-cr`; GitHub credentials are scrubbed and
  fixture telemetry export is off. Runs are serial.
- Results go to `build/evals/finding-resolution/<run-id>/`: `summary.md`,
  `summary.json` and per-run `run.json`. External runs also retain `request.json`,
  normalized `result.json` when valid, and local `runner.stdout` / `runner.stderr`.
  Raw process output may contain sensitive diagnostics and is not copied into
  public summaries or telemetry.
- External evaluations load config once, save the normalized `runner-config.json`
  snapshot and record its full `runner_config_sha256` in the summary. Reports
  preserve this hash and the actual `timeout_s`; they do not reload a changed
  config file. Both values must match across comparison groups.

### External runner contract

Provide an executable that handles one fixture, with an explicit argv config:

```json
{
  "schema_version": "finding-eval-runner.v1",
  "command": ["your-eval-runner", "--your-option"]
}
```

This command runs directly, without shell expansion, in the fixture checkout.
It receives one JSON request on stdin:

```json
{
  "schema_version": "finding-eval-request.v1",
  "repo": "eval-fixture/nonfinite-shutdown-wait",
  "pr": "351",
  "task": "address",
  "skill_path": ".eval/skill"
}
```

The runner supplies its chosen execution environment, reads the indicated skill
snapshot and handles the requested PR through the runtime. Any host-specific
skill exposure or transcript normalization belongs to that runner. It inherits
the fixture's fake GitHub, writable state directory and runtime executable;
do not replace those with real GitHub credentials or another runtime.

Write exactly one result object to stdout; other logs belong on stderr:

```json
{
  "schema_version": "finding-eval-result.v1",
  "identity": "eval-worker",
  "steps": [
    {"command": "address", "codes": ["WAITING_FOR_SIMPLE_ADDRESS"], "exit_code": 5},
    {"command": "final-gate", "codes": ["PASSED"], "exit_code": 0}
  ],
  "cost_usd": 0
}
```

Identity, steps and optional cost are self-reported observations. Independent
graders still check the real fixture state; a result saying `PASSED` cannot
make unfinished handling pass. A nonzero runner exit or invalid result fails
the attempt even if the fixture was otherwise completed. Failures and timeouts
remain in the results, and the runner's process group stops before grading.

Config objects have exactly `schema_version` and `command`; the config size
limit is 64 KiB, with 1–64 nonempty, NUL-free argv strings of at most 8192
characters each. Results require `schema_version`, `identity` and `steps`,
with only optional `cost_usd`; result size is limited to 1 MiB. Identity is a
1–64 character label using letters, digits, dot, underscore or hyphen, starting
with a letter or digit. Keep credentials out of config arguments and labels.

There are at most 1000 steps. Each has exactly `command`, `codes` and
`exit_code`: a command label from the harness's public command vocabulary,
up to 16 uppercase reason-code labels of at most 64 characters, and an integer
exit code from -255 to 255. Cost must be finite and nonnegative. Unsupported
versions, duplicate JSON keys, extra fields and malformed output fail explicitly.

The previous provider-specific mode and model, turns, API-budget and tool-list
flags are removed; they fail rather than selecting a hidden compatibility path.
Executor-specific settings belong outside this harness.

Do not switch branches or edit this checkout while an eval runs. Only the skill
is snapshotted. The runtime is an editable install of `src/`, and the samples,
oracles, and fakes are read from the checkout by every run. A run that ends with
any of these changed since the eval started records `checkout_changed`. The
summary lists those runs in a warning, because they did not measure the commit
the summary names. To keep developing during an eval, run it from a separate
worktree with its own virtual environment.

## Reading results

A run passes when all three criteria hold:

- **legal_state**:
  - `final-gate` passed, read from the latest session's own workspace or archive (an older session's PASSED does not count);
  - that gate saw the final pushed head (a push after the gate fails this);
  - the session that recorded the handling also passed its gate (`handling_session_gated`). Handling evidence is read from that session. A rerun of `final-gate` after a pass opens a fresh, empty session, and that session must not hide the evidence;
  - every thread is resolved and replied to;
  - every reply is in the runtime evidence ledger;
  - the agent made no direct `gh` writes;
  - the fake modelled every runtime call.
- **effective_fix**:
  - dispositions match the sample;
  - the fixture's tests and the oracle pass on the pushed head.
- **consistent_evidence**:
  - every fix cites a commit in the PR and carries validation evidence;
  - at each fix's cited commit, that finding's own oracle cases pass (`oracle_tests` in `sample.json`; default: the whole oracle), so one wrong citation fails even if another finding cites a later commit;
  - runnable recorded validation commands pass on the pushed head.

The summary reports four evidence numbers. Their units differ: five samples
hold six threads, so five repeats give 25 runs, 25 fix items, and 20 runs that
expect a fix.

- **Evidence consistency**: the gated criterion above. It counts runs.
- **Evidence rerunnability**: fixes whose recorded validation the grader could re-run. It counts fixes.
- **Verified remediation**: runs that passed and whose every fix's validation re-ran, over runs that produced an accepted fix. It measures evidence completeness and is conditional: a run that fails before any fix leaves the denominator.
- **Fix attempt success**: the same numerator over every run whose sample expects a fix, early failures included. Compare versions with this one, so that failing sooner cannot raise the score.

A label-only record is visible in these numbers without being scored as a failed fix.

**Workflow deviations** lists each reason code off the documented path. For
every code it shows the runs where the code appeared, the step that hit it, the
step the agent ran next, and how many of those runs still passed. A code that
repeats across runs points at guidance or a state contract, not at a missing
recovery branch. `report` aggregates the normalized steps already saved in
`run.json`; it never parses a vendor transcript or changes stored observations.

The **Rerunnable evidence** column is reported but does not gate a run. It counts
fixes whose recorded validation names a command the grader can re-run. A
`unittest X` entry counts as `python -m unittest X`. A label-only entry such as
`unit-tests=passed` is still accepted by the runtime, but the candidate skill
guidance in PR #374 requires the command actually run. Label-only evidence cannot be
re-verified.

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

## Re-reporting versus re-grading

`report` re-derives deviations and summary numbers from each run's normalized
`run.json`. It does not rebuild git state, reinterpret raw logs, or rerun
oracles. Fixtures are deleted after grading unless the run used `--keep`. A
grader change therefore needs kept fixtures or a fresh run of the affected
samples; results graded before the change stay a baseline of the older grader.

For a before/after comparison, fix the same runtime, grader, external runner
configuration and execution settings for both groups, and change only the
skill snapshot. Keep fixtures and compare the actual recorded hashes. An
unavailable executor means measurement is pending; it is not a prerequisite
for unrelated runtime work, nor a reason to choose a fixed replacement vendor.
Scripted reference results validate the harness and do not demonstrate a
real-agent improvement for PR #374.
