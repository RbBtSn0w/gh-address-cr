# Architecture

## Runtime / Skill Split

The deterministic implementation belongs to the runtime package:

- console entrypoint: `gh-address-cr`
- module entrypoint: `python3 -m gh_address_cr`
- source package: `src/gh_address_cr/`

The packaged skill remains under `skill/` and acts as a thin adapter:

- `skill/SKILL.md` explains agent behavior
- `skill/runtime-requirements.json` declares runtime compatibility
- `skill/agents/` and `skill/references/` provide hints and reference docs

The runtime must be available or execution must fail loudly before mutating session state. Runtime state machines, leases, GitHub side effects, evidence ledgers, and final-gate behavior must not be reimplemented as skill-owned workflow code.


## First-Principles Runtime Kernel

The project treats PR review resolution as a runtime kernel, not as a sequence
of agent-authored patches. External facts enter the runtime first; current state
and safe actions are derived from those facts.

The intended flow is:

```text
external facts -> events -> projections -> policy -> command plan/outbox
-> execution evidence -> events -> final-gate proof
```

- **External facts**: GitHub review threads, pending reviews, check state,
  normalized findings, agent submissions, lease changes, telemetry observations,
  and artifact writes.
- **Events / documented inputs**: append-only facts or explicitly documented
  inputs that can be replayed or reloaded without agent memory.
- **Projections**: derived current views such as actionable work items,
  lease-recovery state, telemetry coverage, and final-gate readiness.
- **Policy**: explicit status-to-action maps, decision tables, or deterministic
  functions over projections.
- **Command plan / outbox**: GitHub reply, resolve, publish, archive, and
  artifact writes are planned side effects, not hidden state transitions.
- **Execution evidence**: a side effect affects completion only after the
  runtime records durable evidence such as reply URLs, resolve confirmation,
  audit events, or final-gate proof.

Artifacts are evidence and reporting outputs. They are not authoritative state
unless a feature explicitly models them as a versioned event source with
contract tests. Telemetry reports must avoid self-referential completion
semantics; when the reporting write itself would change the measurement, the
contract must define the excluded reporting boundary or use a
non-self-referential artifact.

Any feature touching runtime state, telemetry, final-gate behavior, leases,
artifacts, GitHub IO, session persistence, or the structured agent protocol must
complete Architecture Preflight before implementation. Repeated feedback that
adds branches in the same design axis is a signal to update the architecture
spec instead of continuing to expand conditionals.


## PR Session Architecture

`gh-address-cr` ships the session engine inside the runtime package and exposes supported workflows through the public `gh-address-cr` entrypoint.

The implementation model is now:

- Python owns the stateful logic and GitHub/local-review orchestration.
- `gh-address-cr` is the only stable automation entrypoint for runtime work.
- Tests are organized around Python behavior first, then CLI syntax compatibility.

- `github_thread` items are synced from GraphQL thread snapshots.
- `local_finding` items are ingested from a local review adapter.
- local findings can be explicitly handled in-session with `gh-address-cr agent fix`, `gh-address-cr agent fix-all`, or `gh-address-cr submit-action`.
- `gh-address-cr final-gate` evaluates both:
  - session blocking item count
  - unresolved GitHub thread count
  - terminal GitHub thread reply-evidence count
  - current-login pending review count
  - optional PR checks when `--require-checks` or `--require-required-checks` is supplied

The session state is stored in a PR-scoped workspace under the user cache directory:

- workspace: `<owner>__<repo>/pr-<pr>/`
- session: `session.json`
- GitHub snapshots: `threads.jsonl`
- handled threads: `handled_threads.txt`
- audit log: `audit.jsonl`
- trace log: `trace.jsonl`
- audit summary: `audit_summary.md`
- runtime telemetry: `telemetry/runtime.jsonl`
- imported external telemetry: `telemetry/agent.jsonl`
- telemetry import ledger: `telemetry/imports.jsonl`
- telemetry fingerprint ledger: `telemetry/fingerprints.json`
- efficiency report: `efficiency_report.json`
- findings: `findings-*.json` and `code-review-findings.json`
- replies: `reply-*.md`
- loop requests: `loop-request-*.json`
- validation records: `validation-*.json`

`session.json` owns command-to-command handoff state. In addition to local and
GitHub work items, `handoff.producer_results` records source-scoped producer
submissions so a later plain `review` command can continue the same PR session
after `findings --input <path>|- --source <producer>` succeeds, including
explicit empty `[]` results.

If `gh-address-cr final-gate --auto-clean` passes, the current PR workspace is archived before deletion under:

- archive root: `archive/<owner>__<repo>/pr-<pr>/<run_id>/`

To inspect one run after the fact, use:

```bash
gh-address-cr final-gate --no-auto-clean <owner/repo> <pr_number>
```

The session also tracks loop-safety metadata per item:

- `repeat_count`: how many times the same local finding was re-ingested
- `reopen_count`: how many times a previously closed/deferred/clarified item was reopened
- claim lease fields so stale ownership can be reclaimed


## Telemetry Evidence Boundary

Telemetry is PR-scoped observed workflow evidence. It can enrich final-gate
output, `audit_summary.md`, and `efficiency_report.json`, but it does not mutate
review item state and does not replace reply, resolve, or final-gate proof.

The runtime owns telemetry normalization and reporting:

- runtime events are recorded by `gh-address-cr` itself
- external agent events are imported through `gh-address-cr telemetry ingest`
- final-gate may import host telemetry from `GH_ADDRESS_CR_HOST_TELEMETRY_INPUT`
- accepted events keep source attribution and runtime-computed `event_fingerprint`
  values
- duplicate or overlapping events are deduplicated before report statistics are
  calculated
- every efficiency summary reports `complete`, `partial`, `runtime-only`, or
  `unavailable` coverage

Telemetry commands fail loudly for malformed, unsafe, unsupported, or ambiguous
telemetry input. Core review-resolution flows remain fail-open for missing or
damaged telemetry and report the reduced coverage instead of blocking review
completion.


## Runtime Complexity Boundary Contracts

The runtime owns the explicit contracts used to reduce workflow complexity:

- `WorkItemHandlingBoundary`: declares which work item kinds a runtime boundary
  can handle, the required evidence, completion criteria, failure reasons, and
  safe next actions. Boundary selection is runtime-owned and deterministic.
- `LeaseRecoveryState`: declares whether an expired or stale lease can `renew`,
  `reclaim`, `refresh_state`, `stop`, or report `already_completed`.
- `TelemetryCoverageState`: records coverage, source attribution, diagnostics,
  privacy status, report location, and measured telemetry overhead.
- `LogicValidationSignal`: records advisory or blocking consistency risks for
  evidence gaps, state contradictions, and unsupported completion claims.
- `DeliverySlice`: records phased implementation scope and acceptance evidence
  so complexity work can ship in independently verifiable increments.

These models are additive public contract vocabulary. They do not change the
rule that `session.json`, reply evidence, resolve state, and `final-gate` remain
the authoritative completion truth.

Execution boundaries:

- Work item handler selection happens before an `ActionRequest` is written. The
  migrated GitHub review-thread fix path reports `github-thread-fix`; unmigrated
  paths keep existing behavior and omit `handling_boundary`.
- Lease recovery is computed from current runtime truth. It advises agents to
  renew, reclaim, refresh state, stop, or treat work as already completed; it
  never permits stale responses to overwrite accepted, transferred, or changed
  work.
- Telemetry reports include measured overhead and emit
  `TELEMETRY_OVERHEAD_EXCEEDED` when report construction crosses the 250ms
  normal-path budget. The runtime-returned report owns the final measured
  overhead; the persisted JSON artifact is written once and may leave that
  field unset rather than performing an unmeasured self-rewrite. Core completion
  remains fail-open for telemetry degradation, while telemetry-specific commands
  stay fail-loud.
- Logic validation signals are lightweight consistency checks. Blocking signals
  can fail final-gate; advisory signals are surfaced for explanation without
  becoming a second review producer.


## Runtime Package Layout

The main logic lives in the Python runtime package under `src/gh_address_cr/`.

- `cli.py`: console entrypoint and runtime command dispatch
- `core/`: session state, workflow transitions, final-gate, and orchestration helpers
- `github/`: GitHub CLI IO and failure diagnostics
- `intake/`: findings parsing and normalization
- `commands/`: current internal command modules behind supported public commands

New automation should use `gh-address-cr`, not direct script paths.

The runtime package requires Python 3.10+ because the implementation uses modern typing syntax such as `list[str]` and `str | None`.

The `gh-address-cr` console script is the stable automation surface.

Unified CLI examples:

```bash
gh-address-cr review owner/repo 123
gh-address-cr address owner/repo 123 --lean
gh-address-cr final-gate --no-auto-clean owner/repo 123
gh-address-cr review owner/repo 123 --input -
gh-address-cr findings owner/repo 123 --input -
gh-address-cr agent fix owner/repo 123 local-finding:<fingerprint> --commit <sha> --files src/example.py --summary "Fixed locally." --why "Confirmed finding." --validation "python3 -m unittest=passed"
```


## Repository Layout Model

This git repository is the development and release wrapper around one shipped skill.

- Published skill payload: the entire `skill/` directory
- Repo-level verification harness: `tests/`
- Repo-level release and contributor files: `.github/`, `pyproject.toml`, `CHANGELOG.md`, root `AGENTS.md`, and other top-level metadata

Path convention:

- Repo-level docs and commands that execute runtime workflows use `gh-address-cr`
- Skill-owned docs inside `skill/` use paths relative to the skill root, such as `references/...` and `agents/openai.yaml`

If a rule or instruction must ship with the installed skill, it must live inside `skill/`, not only at repository root.


## Skill folder

- `skill/`
  - `SKILL.md`
  - `agents/openai.yaml`
  - `assets/reply-templates/*`
  - `references/cr-triage-checklist.md`
  - `runtime-requirements.json`


## What this skill provides

- PR-scoped session state for GitHub threads and local findings
- Strict per-item CR handling workflow
- Required worker evidence format (files/test result/reviewer-facing rationale) with publish-time commit evidence hydration
- Mandatory final gate (`gh-address-cr final-gate`) before completion
- Session-scoped state tracking to avoid duplicate work
- Audit log + trace log + audit summary + summary hash output
- Audit summaries and `final-gate` output preserve machine-readable gate counts and summary hashes for evidence
- Python-first implementation with a single CLI entrypoint
- Module-split automated tests for session, wrappers, and helper scripts
