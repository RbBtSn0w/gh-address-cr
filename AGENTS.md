# AGENTS.md

> This file owns architecture governance and day-to-day agent execution rules.
> Static design references live in `docs/rfcs/`; they do not select active work.

## Repository Model

This repository has two different scopes. Do not blur them:

- **Repository root**: Development, verification, CI, release metadata, and contributor guidance.
- **`skill/`**: The installable and published skill folder.

The released skill payload is the entire `skill/` directory. Files such as `tests/`, `.github/`, `pyproject.toml`, `README.md`, and this `AGENTS.md` support development and release, but are not part of the installed skill.

The payload directory name is `skill/`, but the product/runtime identity remains
`gh-address-cr`: the Python package, console entrypoint, repository URL,
`SKILL.md` frontmatter `name`, and `/gh-address-cr` invocation must not be
renamed to `skill`. Skills installer examples should select the payload folder
with `--skill skill`.

## Telemetry

- **OpenTelemetry (OTel)**: For every new feature or requirement added, ensure you implement corresponding OpenTelemetry instrumentation (spans, events, or metrics) to maintain observability.
- **OTel CLI Compliance**: All CLI programs and external subprocess wrappers must strictly follow the official [Semantic conventions for CLI programs](https://opentelemetry.io/docs/specs/semconv/cli/cli-spans/):
  - Use `SpanKind.INTERNAL` for the CLI's own execution (callee spans) and `SpanKind.CLIENT` for subprocess calls (caller spans).
  - Span names must default to `{process.executable.name}` (e.g. `"git"`, `"claude"`) or documented low-cardinality values.
  - Correctly record all **Required** attributes: `process.executable.name`, `process.exit.code`, and `process.pid`.
  - Correctly record `error.type` on failure spans (when `process.exit.code !== 0`) as **Conditionally Required**.
- **Telemetry Privacy**: **All telemetry data must comply with privacy standards**—never log raw file paths, personally identifiable information (PII), or user secrets/tokens. Sanitization is mandatory before collecting `process.command_args`: CLI argv goes through `sanitize_cli_argv`, which keeps only the executable basename and the recognized command token and redacts every other argument. Subprocess argv goes through `command_label`, which keeps the executable basename, a `python -m <module>` prefix when one is present, and at most one safe positional token, dropping every other flag and flag value; or through `subprocess_operation`, which reduces the command to a bounded category name and retains no argument at all.

## Scope and Authority

Follow this order of precedence:
1. Direct system, developer, and user instructions.
2. This `AGENTS.md` (Architecture, Governance & Execution).
3. Executable repository contracts in `tests/`.
4. Static design references in `docs/rfcs/` (historical context only).

## Infrastructure Guidelines

### Compatibility Policy
- Preserve or explicitly version public CLI, machine-readable, and packaged-skill contracts when changing behavior.
- Remove deprecated or legacy compatibility paths only when the replacement contract is documented, tested, and versioned as public behavior, or when direct instructions explicitly require removal.
- Prefer a clean current contract over hidden shims, aliases, or fallback branches kept only for historical behavior.

### CLI and Skill Evolution Policy
- Treat this CLI as local-first tooling while keeping public CLI and machine-readable contracts stable or explicitly versioned.
- Treat the published `skill/` payload with the same standard: current guidance may evolve, but public agent-facing behavior must remain documented and tested.
- Do not spend maintenance effort on hidden historical compatibility unless a preserved or versioned public contract requires it.
- When CLI or skill behavior is modernized, update obsolete flags, pathways, references, and compatibility glue in the same documented contract change.

### Python Environment
- **Version**: Python 3.10+ (enforced by `pyproject.toml`).
- **Install for dev**: `pip install -e .` (required; test discovery depends on the installed package).

### Testable Contracts And Fail-Fast Changes
Public behavior changes MUST update code, docs, and executable tests together. The project MUST fail fast on missing tools, malformed producer output, invalid handoff formats, unsafe resolve-only handling, and unsupported public command usage. Silent fallbacks, hidden compatibility shims, alternate prompt contracts, and narrative-only findings ingestion are forbidden unless they are explicitly documented, tested, and versioned as public behavior.

### Verification Commands
Before claiming work is complete, run these local checks:
- **Install**: `pip install -e .` (required before running tests).
- **Linting**: `ruff check src tests scripts/build_plugin_payload.py` (configured in `pyproject.toml`).
- **Type Checking**: `python3 scripts/check_mypy_ratchet.py` (CI blocking gate; baseline 0 errors, config in `pyproject.toml`). Run it with the same interpreter that has the package installed so third-party stubs resolve.
- **Unit Tests**: `python3 -m unittest discover -s tests`.
- **CLI Smoke Test**: `python3 -m gh_address_cr --help`.
- **Agent Contract Smoke Test**: `python3 -m gh_address_cr agent manifest`.
- **Plugin Payload Checks**: `python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr` and `python3 scripts/build_plugin_payload.py --check`.

### Git Workflow
- **Status Check**: Always run `git status` before starting work.
- **Commit Format**: Use Conventional Commits (e.g., `feat:`, `fix:`, `docs:`, `refactor:`).
- **History**: Propose a draft commit message. Do not stage/commit unless explicitly requested.

## Path Conventions

- **In repo-root docs/tests**: Use repo-root paths like `src/gh_address_cr/cli.py`.
- **In skill-owned docs (`skill/`)**: Use skill-root-relative paths like `references/...` and `agents/openai.yaml`.
- **Do not rename product identifiers**: Use `gh-address-cr` for the runtime CLI, PyPI package, GitHub repository, skill name, and slash command.

## Execution Discipline

- **Read first**: Read relevant contracts in `README.md`, this file, and relevant executable contracts before editing.
- **Verify first**: Confirm current behavior or reproduce bugs before proposing fixes.
- **Fail fast**: Do not add silent fallbacks or hidden behavior changes.
- **Smallest change**: Default to the smallest safe change. Avoid opportunistic refactors.
- **Contract discipline**: If a public or agent-facing contract changes, update docs and tests together.
- **Skill/runtime feedback**: When the `gh-address-cr` workflow itself blocks progress because of a repeatable skill/runtime gap, use `python3 -m gh_address_cr submit-feedback ...` against this repository instead of burying the problem in PR findings or local notes.

### Architecture Preflight Gate

Before editing implementation code, complete an Architecture Preflight when a
change crosses a **blast-radius trigger**: it expands runtime state space,
introduces or reshapes telemetry ingestion/reporting contracts, changes
`final-gate` truth semantics, alters lease/orchestration ownership, adds new
artifact-backed decision surfaces, widens GitHub side effects, changes session
persistence semantics, changes Status-to-Action Map behavior, or introduces a
new structured agent protocol surface. Small local fixes that stay within the
existing protected baseline do not require the full preflight. When the trigger
fires, the preflight must identify:

- authoritative state owner
- external facts or event inputs
- projection or derived-state shape
- policy table, status-to-action map, or deterministic decision function
- side-effect command plan or outbox boundary
- artifact truth boundary and telemetry/reporting self-reference risks
- recovery, replay, and executable contract tests

If review or implementation feedback repeatedly adds edge branches in the same
design axis without reducing the state space, stop expanding conditionals and
create or update an architecture spec instead. Local bug fixes are acceptable
only when they reduce ambiguity or remove a branch; they must not introduce
unmodeled state flags, hidden fallback paths, artifact-backed truth, or new
layers that exceed the protected baseline without a recorded blast-radius
justification.

## Automated Agent PR Policy

Third-party review bots open PRs against this repository. The rulings below are
standing decisions. Check them before opening a performance or security PR: a
re-proposal of a change a ruling already covers will be closed.

### Standing rulings

- **`cr_metrics.build_cr_summary` uses `dict.setdefault` intentionally.**
  Rewriting it as `if key not in mapping: mapping[key] = []` pushes the function
  past the ruff `C901` complexity cap (15) and forces a `# noqa: C901`
  suppression. `src/` carries zero in-code lint suppressions and that is a
  deliberate invariant. The input is a single PR's evidence ledger (tens to low
  hundreds of rows), not a hot loop. Do not re-propose without profiling
  evidence and a version that stays under the complexity cap.

- **CLI argv sanitization is owned by `sanitize_cli_argv`.** It redacts every
  token except the executable basename and the recognized command token, so
  per-flag redaction logic (`--token secret` versus `--token=secret`) is
  unnecessary in the telemetry-safety layer. `safe_command_args`, the
  unreferenced per-flag redactor that drew eight such PRs (#233, #236, #237,
  #238, #244, #245, #247, #249), was removed in #241 — there is no per-flag
  redactor to patch, and adding one back is not a fix. Subprocess-side
  telemetry is bounded for the same reason: see the Telemetry Privacy rule
  above for exactly what `command_label` and `subprocess_operation` retain.

- **No repository-wide reformatting.** Line width and formatting follow
  `pyproject.toml`. A PR that re-wraps files unrelated to its stated change is
  closed regardless of the change's merit.

### Agent journal files

Do not add `.jules/` or equivalent per-persona journal files to a PR branch.
They are created fresh on every run and never land on the default branch, so
they carry nothing forward and produce the same finding repeatedly. Durable
agent guidance belongs in this file.

## Completion Standard

A task is complete only when:
- The requested change is implemented and verified.
- The relevant contract docs remain consistent.
- `final-gate` passes (for PR-session handling work).
- PR-session completion evidence includes the readable `final-gate` metrics summary
  (`completion_summary.markdown`, or the rendered Markdown within
  `PR Completion Summary Guidance`) with telemetry coverage and report
  artifacts. Telemetry failures are fail-open for review completion, but
  telemetry diagnostics must remain visible.
- No unresolved high-severity issues were introduced.

## Architecture Rules

### I. Control Plane Owns Runtime State

`gh-address-cr` is a PR-scoped control plane for AI coding agents. Runtime
state, intake routing, GitHub side effects, reply evidence, session metrics,
loop safety, and final gating MUST be owned by deterministic code. Each PR
session MUST have exactly one deterministic, versioned persistence boundary
designated as its authoritative runtime store. Markdown
files and agent hints MAY describe how to use the system, but they MUST NOT be
the authoritative implementation of state transitions or completion checks.
Telemetry state, import ledgers, fingerprint ledgers, coverage calculations,
efficiency report artifacts, and telemetry diagnostics MUST also be owned by
the runtime.

The currently designated store remains authoritative until a versioned
migration atomically designates its replacement. Compatibility files, reports,
materialized views, and other artifacts MUST be derived projections and MUST
NOT accept authoritative writes. A persistence-authority migration MUST
preserve recovery and replay, fail loudly on divergence, and MUST NOT permit
dual-primary operation.

Orchestration state, including leases and active worker queues, MAY be
materialized for resume and delivery, but it remains subordinate to the
authoritative runtime store. It MUST NOT independently own lease-conflict,
expiry, status, or release policy, and the control plane MUST reconcile it from
runtime truth before every major action. `runtime.sqlite3` is the current authoritative store; `session.json` and
evidence/report files are derived compatibility projections.


### II. CLI Is The Stable Public Interface

High-level CLI commands are the only agent-safe public surface. The interaction
between the agent and the control plane MUST follow the **Structured Agent Protocol**,
using formal `ActionRequest` and `ActionResponse` schemas. The control plane MUST
provide a stable **Status-to-Action Map** that derives safe next actions or stop
conditions from machine-readable summaries. The main public entrypoint is `review`;
advanced entrypoints such as `threads`, `findings`, `adapter`,
`review-to-findings`, `telemetry ingest`, and `telemetry summary` MAY exist for
explicit integrations but MUST NOT replace `review` as the default orchestration
path. Machine-readable outputs, reason codes, wait states, exit codes, cache
artifacts, and stable input contracts MUST be preserved or versioned when changed.


### III. Evidence-First Review Handling

Every review item MUST be verified before code changes are made. Each item MUST
be classified as `fix`, `clarify`, `defer`, or `reject`; out-of-scope work MUST
be deferred with rationale instead of silently stretching the current PR. GitHub
review threads require both reply and resolve. Terminal GitHub threads require
durable reply evidence from the current authenticated GitHub login, including a
concrete reply URL. Local findings require an explicit terminal handling note.
Completion MUST NOT be claimed until `final-gate` passes for the current PR
session.


### IV. Packaged Skill Boundary Is Explicit

This repository has two scopes: the source repository and the packaged skill
payload under `skill/`. Do not blur them:
- **Repository root**: Development, verification, CI, release metadata, and contributor guidance.
- **`skill/`**: The installable and published skill folder.

The **Deterministic Runtime** MUST be physically
separated from the packaged skill adapter. The skill adapter MUST remain a **Thin
Layer** that acts as a router and a **Behavioral Policy Layer**. It MUST explain
how to use the runtime safely but MUST NOT contain authoritative business logic,
state-machine transitions, or direct implementation of side effects.

Path language MUST match the active scope. Repo-root docs and commands use
paths such as `src/gh_address_cr/cli.py`; skill-owned docs use
paths such as `references/...` and `agents/openai.yaml`.


### V. Testable Contracts

Public behavior changes MUST update code, docs, and executable tests together.
Silent fallbacks, hidden compatibility shims, alternate prompt contracts,
and narrative-only findings ingestion are forbidden unless they are explicitly
documented, tested, and versioned as public behavior.
Telemetry safety, source attribution, event fingerprinting, duplicate handling,
coverage labels, fail-open/fail-loud behavior, and final-gate/audit evidence
MUST be covered by executable contract or acceptance tests when changed.


### VI. Multi-Agent Coordination and Claim Leases

When a feature or workflow introduces genuine **multi-agent blast radius**, the
control plane MUST coordinate that work through explicit, item-scoped claim
leases. No agent or process MAY mutate a work item without an active lease. For
that blast-radius class, the system MUST define specialized roles
(coordinator, producer, triage, fixer, verifier, publisher, gatekeeper) and
enforce lease policies (expiry, reclaiming, conflict detection) to ensure
parallel execution is safe and auditable. Single-agent workflows are the
default supported path and MUST NOT be forced to carry orchestration weight
that they do not need.
**The coordination layer (Orchestrator) MUST follow a strict Delegation Pattern:
it manages the fleet and lease lifecycle, but MUST delegate all state transitions
and finding-specific logic to the authoritative Runtime Workflow.**


### VII. External Intake Is Replaceable

`gh-address-cr` productizes **PR Review Resolution**, not review production.
The project MUST remain agnostic of the specific review engine, prompt, or agent
vendor that generates findings. Review intake MUST be governed by the **Normalized
Findings Contract**. The control plane MUST NOT be coupled to a specific review
producer's internal implementation.


### VIII. Telemetry Is Attributed Observed Evidence

Workflow telemetry is observed evidence about agent efficiency and workflow
coverage. It MUST NOT resolve review items, mutate findings, or replace the
reply/resolve/final-gate evidence required by Principle III. Runtime telemetry
and imported external agent telemetry MUST preserve source attribution and MUST
produce an explicit coverage label: `complete`, `partial`, `runtime-only`, or
`unavailable`.

OpenTelemetry tracing of the surviving live workflow is part of the protected
baseline. It MUST remain attached to real business functionality and MUST NOT
survive only as an empty-shell wrapper around removed subsystems.

When a feature or command handles external telemetry ingestion or other
telemetry-specific blast radius, it MUST use a documented, vendor-neutral event
contract. For that blast-radius class, the runtime MUST normalize accepted
events, compute deterministic `event_fingerprint` values after canonicalization,
deduplicate duplicate or overlapping imports by fingerprint or documented
correlation rules, and report accepted, duplicate, rejected, and diagnostic
outcomes without inflating durations, counts, retries, slowest-operation
rankings, or error rates.

Telemetry artifacts MUST be public-safe. Imports MUST reject or sanitize tokens,
credentials, raw prompts, usernames, private machine identifiers, and unnecessary
absolute local paths before storage or reporting. Telemetry-specific commands
MUST fail loudly for malformed, unsafe, unsupported, or ambiguous telemetry.
Core review-resolution flows (`review`, `address`, publish, reply, resolve, and
`final-gate`) MUST remain fail-open for missing or damaged telemetry and surface
`runtime-only`, `partial`, or `unavailable` coverage instead of blocking review
completion.

Workflow telemetry MUST follow a layered model by default: (1) exactly one root
invocation span per short-lived CLI execution serves as the product-timeline
anchor; (2) a workflow step is promoted to a child span ONLY when it owns
independent duration AND at least one of independent count, independent error
boundary, or externally visible product/operational value (the first approved
child-span candidates are `gh_address_cr.adapter` and
`gh_address_cr.command_session.operation`); (3) checkpoint-style phase markers
such as `preflight`, `session`, `ingest`, `gate`, and summary markers remain
span events. Cross-invocation sessions MUST stay correlation-first and MUST NOT
invent synthetic parent-child span links across process boundaries.

This layered model is the DEFAULT governance rule, not an exception-free hard
rule. A deviation — promoting a checkpoint to a span, demoting an approved child
span, or introducing new child spans — is permitted only when it carries
explicit rationale, verification evidence, and reviewer-visible approval criteria
recorded with the change.


### IX. First-Principles Runtime Kernel

Review resolution surfaces that introduce new runtime-state blast radius MUST be
modeled as a first-principles runtime kernel. For that blast-radius class,
external facts such as GitHub review threads, pending reviews, check state,
normalized findings, agent submissions, lease changes, telemetry observations,
and artifact writes MUST enter the system as typed events or documented inputs.
Current state MUST be derived by projections. Policy decisions MUST be
expressed as explicit policy tables, status-to-action maps, or deterministic
functions over projections, not scattered status conditionals. Side effects
MUST be planned as command or outbox entries and MUST become completion
evidence only after execution results are recorded.

Artifacts are evidence and reporting outputs. They MUST NOT become authoritative
truth unless the feature explicitly models them as a versioned event source with
contract tests. Telemetry and reporting MUST avoid self-referential completion
semantics; when exact measurement would require observing the reporting write
itself, the contract MUST define the excluded reporting boundary or use a
non-self-referential artifact.

`final-gate` remains a protected kernel surface and MUST continue to follow
fact -> projection -> policy reasoning even when the broader review-state
machine is simplified.

Any feature whose blast radius touches runtime state, telemetry, final-gate
behavior, leases, artifacts, GitHub IO, session persistence, or the structured
agent protocol in a way that expands state space or public architecture MUST
complete Architecture Preflight before implementation. The preflight MUST name
the state owner, event inputs, projection shape, policy/action map,
side-effect/outbox boundary, recovery and replay model, artifact truth
boundary, and executable contract tests. If repeated review or implementation
feedback in the same design axis requires adding edge branches without reducing
the state space, implementation MUST stop and create or update an architecture
spec instead of continuing to patch conditionals.


### X. Minimal Viable Baseline and Complexity Budget

The protected baseline for this product is the irreducible review-resolution
journey plus OpenTelemetry of that live journey: findings -> classify -> reply + resolve
-> `final-gate`, with deterministic runtime ownership and preserved CLI contracts.
That baseline is the architectural floor.

Any new subsystem, framework, orchestration layer, telemetry plane, migration
meta-layer, or parallel state engine beyond that baseline MUST carry an
explicitly recorded blast-radius justification and explain why the simpler
baseline-preserving alternative was rejected. Complexity added only to manage
another non-retired layer is presumed invalid unless the justification proves
that it reduces long-term state space.


## Runtime Architecture

The intended architecture is:

- Runtime kernel when blast radius requires it: typed external facts, event log
  or documented event inputs, projections, policy engine, Status-to-Action Map,
  command planner, outbox executor, execution evidence, and replay/contract
  tests.
- Core engine: deterministic state machine, GitHub IO, findings normalization,
  session persistence, loop safety, final gate, audit artifacts, and the
  minimum telemetry/reporting required by the protected baseline. Multi-agent
  lease management and advanced telemetry import ledgers remain optional layers
  unless blast radius requires them.
- CLI: stable public interface for agents, humans, CI, and future automation.
- Agent protocol: structured `ActionRequest` and `ActionResponse` schemas
  for `fix`, `clarify`, `defer`, and `reject` workflows.
- Skill: thin usage adapter (Behavioral Policy Layer) that tells an AI agent
  when to invoke the CLI and how to react to machine-readable statuses (Status-to-Action Map).
- External producers: replaceable review sources that emit normalized findings
  JSON or fixed `finding` blocks.
- External telemetry sources: replaceable agent-host or generic event feeds that
  emit observed workflow telemetry, never review-resolution decisions.

The CLI control plane is authoritative. Agent reasoning MAY decide how to fix,
clarify, defer, or reject a specific item, but the CLI MUST own session
transitions, GitHub writes, reply/resolve ordering, and final-gate evaluation.
Telemetry evidence MAY enrich final-gate and audit artifacts, but it MUST NOT
change review item state or completion truth.

The runtime flow MUST remain conceptually traceable as:

```text
external facts -> events -> projections -> policy -> command plan/outbox
-> execution evidence -> events -> final-gate proof
```

## Autonomous Development

Read the smallest governing contract, inspect the current implementation, implement
the requested change, and verify it with reproducible evidence. Plan dynamically;
no generated spec, plan, task checklist, slash command, or workflow manifest is
required. Public behavior changes update code, docs, and executable tests together.
Changes crossing an Architecture Preflight trigger record only the necessary
design decisions in `docs/rfcs/` before implementation. Small local fixes do not
require a design document.

### Risk-Matched Verification

Code changes MUST run the smallest verification that matches the scope. Public
CLI or packaging changes MUST include CLI smoke tests. Session, loop, reply,
resolve, or final-gate changes MUST include behavior tests. Documentation-only
changes MUST check repo-root versus skill-root paths and public contract consistency.

Telemetry changes crossing the telemetry blast-radius threshold MUST include
tests for safety filtering, deterministic fingerprints, duplicate or overlapping
imports, coverage labels, report artifacts, final-gate/audit integration, and
the fail-loud telemetry-command versus fail-open core-workflow boundary.

Runtime-kernel changes crossing the kernel blast-radius threshold MUST include
replay or contract tests proving that event inputs, projections, policy decisions,
side-effect plans, artifact boundaries, and final-gate outcomes agree.

Static RFCs are reference material, not active-task pointers or runtime truth.
Their historical status and implementation claims must be checked against current
code and tests. New work follows the user's request and current contracts.
Governance changes explain the reason, affected constraints, and verification in
the change description; template synchronization and constitution version bumps
are not required. Preserve the protected baseline and justify additional layers.
