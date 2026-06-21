<!--
Sync Impact Report
Version change: 1.5.0 -> 1.5.1
Amendment reason:
- Correct stale path reference to cli.py in Principle IV.
Version bump rationale:
- PATCH: Corrected stale path reference in Principle IV.
Modified principles:
- IV. Packaged Skill Boundary Is Explicit (corrected path reference)
Added sections:
- None
Removed sections:
- None
Templates requiring updates:
- None: ✅ updated
Runtime guidance requiring updates:
- None: ✅ updated
Follow-up items:
- None
-->
# GH Address CR Constitution

## Core Principles

### I. Control Plane Owns Runtime State

`gh-address-cr` is a PR-scoped control plane for AI coding agents. Runtime
state, intake routing, GitHub side effects, reply evidence, session metrics,
loop safety, and final gating MUST be owned by deterministic code. Markdown
files and agent hints MAY describe how to use the system, but they MUST NOT be
the authoritative implementation of state transitions or completion checks.
Telemetry state, import ledgers, fingerprint ledgers, coverage calculations,
efficiency report artifacts, and telemetry diagnostics MUST also be owned by
the runtime.
**Orchestration state (leases, active worker queues) is a volatile, transient
shadow of the authoritative Runtime state (`session.json`). The control plane
MUST reconcile orchestration state from the runtime truth before every major
action.**

Rationale: PR review handling has external side effects and resumable state.
The workflow must be auditable after interruptions and reproducible without
depending on an agent's conversational memory.

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

Rationale: AI agents, humans, CI, and future agent runners need the same stable
control boundary. Formal protocols and status mapping separate cognitive reasoning
from side-effect execution and prevent agents from "guessing" the next command.

### III. Evidence-First Review Handling

Every review item MUST be verified before code changes are made. Each item MUST
be classified as `fix`, `clarify`, `defer`, or `reject`; out-of-scope work MUST
be deferred with rationale instead of silently stretching the current PR. GitHub
review threads require both reply and resolve. Terminal GitHub threads require
durable reply evidence from the current authenticated GitHub login, including a
concrete reply URL. Local findings require an explicit terminal handling note.
Completion MUST NOT be claimed until `final-gate` passes for the current PR
session.

Rationale: A zero unresolved-thread count is not enough. The control plane must
prove that the agent responded, resolved, and left recoverable evidence.

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

Rationale: The project ships a skill. Blurring repo-root and skill-root paths
creates broken installed instructions and unstable agent behavior. Physical
separation and the policy-layer model prevent runtime-logic drift within the
skill payload.

### V. Testable Contracts

Public behavior changes MUST update code, docs, and executable tests together.
Silent fallbacks, hidden compatibility shims, alternate prompt contracts,
and narrative-only findings ingestion are forbidden unless they are explicitly
documented, tested, and versioned as public behavior.
Telemetry safety, source attribution, event fingerprinting, duplicate handling,
coverage labels, fail-open/fail-loud behavior, and final-gate/audit evidence
MUST be covered by executable contract or acceptance tests when changed.

Rationale: Agent workflows amplify ambiguity. A weak fallback can create false
completion claims, duplicate side effects, or unrecoverable session drift.

### VI. Multi-Agent Coordination and Claim Leases

The control plane MUST coordinate multi-agent work through explicit, item-scoped
claim leases. No agent or process MAY mutate a work item without an active lease.
The system MUST define specialized roles (coordinator, producer, triage, fixer,
verifier, publisher, gatekeeper) and enforce lease policies (expiry, reclaiming,
conflict detection) to ensure parallel execution is safe and auditable.
**The coordination layer (Orchestrator) MUST follow a strict Delegation Pattern:
it manages the fleet and lease lifecycle, but MUST delegate all state transitions
and finding-specific logic to the authoritative Runtime Workflow.**

Rationale: PR repair is often multi-dimensional. Without explicit ownership,
parallel agents can overwrite each other, resolve without evidence, or claim
completion from stale state. Delegation prevents "state drift" between the
orchestrator and the engine.

### VII. External Intake Is Replaceable

`gh-address-cr` productizes **PR Review Resolution**, not review production.
The project MUST remain agnostic of the specific review engine, prompt, or agent
vendor that generates findings. Review intake MUST be governed by the **Normalized
Findings Contract**. The control plane MUST NOT be coupled to a specific review
producer's internal implementation.

Rationale: Specializing in resolution prevents scope creep and ensures the
orchestration layer remains a stable boundary for any review tool that can
emit the accepted findings format.

### VIII. Telemetry Is Attributed Observed Evidence

Workflow telemetry is observed evidence about agent efficiency and workflow
coverage. It MUST NOT resolve review items, mutate findings, or replace the
reply/resolve/final-gate evidence required by Principle III. Runtime telemetry
and imported external agent telemetry MUST preserve source attribution and MUST
produce an explicit coverage label: `complete`, `partial`, `runtime-only`, or
`unavailable`.

External telemetry ingestion MUST use a documented, vendor-neutral event
contract. The runtime MUST normalize accepted events, compute deterministic
`event_fingerprint` values after canonicalization, deduplicate duplicate or
overlapping imports by fingerprint or documented correlation rules, and report
accepted, duplicate, rejected, and diagnostic outcomes without inflating
durations, counts, retries, slowest-operation rankings, or error rates.

Telemetry artifacts MUST be public-safe. Imports MUST reject or sanitize tokens,
credentials, raw prompts, usernames, private machine identifiers, and unnecessary
absolute local paths before storage or reporting. Telemetry-specific commands
MUST fail loudly for malformed, unsafe, unsupported, or ambiguous telemetry.
Core review-resolution flows (`review`, `address`, publish, reply, resolve, and
`final-gate`) MUST remain fail-open for missing or damaged telemetry and surface
`runtime-only`, `partial`, or `unavailable` coverage instead of blocking review
completion.

Rationale: The runtime cannot assume every agent host exposes complete telemetry.
Honest coverage labels, source attribution, and privacy filtering let efficiency
reports guide optimization without overstating evidence or leaking host data.

### IX. First-Principles Runtime Kernel

Review resolution MUST be modeled as a first-principles runtime kernel. External
facts such as GitHub review threads, pending reviews, check state, normalized
findings, agent submissions, lease changes, telemetry observations, and artifact
writes MUST enter the system as typed events or documented inputs. Current state
MUST be derived by projections. Policy decisions MUST be expressed as explicit
policy tables, status-to-action maps, or deterministic functions over
projections, not scattered status conditionals. Side effects MUST be planned as
command or outbox entries and MUST become completion evidence only after
execution results are recorded.

Artifacts are evidence and reporting outputs. They MUST NOT become authoritative
truth unless the feature explicitly models them as a versioned event source with
contract tests. Telemetry and reporting MUST avoid self-referential completion
semantics; when exact measurement would require observing the reporting write
itself, the contract MUST define the excluded reporting boundary or use a
non-self-referential artifact.

Any feature that touches runtime state, telemetry, final-gate behavior, leases,
artifacts, GitHub IO, session persistence, or the structured agent protocol MUST
complete Architecture Preflight before implementation. The preflight MUST name
the state owner, event inputs, projection shape, policy/action map,
side-effect/outbox boundary, recovery and replay model, artifact truth boundary,
and executable contract tests. If repeated review or implementation feedback in
the same design axis requires adding edge branches without reducing the state
space, implementation MUST stop and create or update an architecture spec
instead of continuing to patch conditionals.

Rationale: Agent workflows fail when external facts, derived state, decisions,
side effects, and evidence are blended in one imperative path. Modeling facts
first and deriving actions from projections prevents unbounded boundary growth
and makes the system replayable, testable, and maintainable.

## Runtime Architecture

The intended architecture is:

- Runtime kernel: typed external facts, event log or documented event inputs,
  projections, policy engine, Status-to-Action Map, command planner, outbox
  executor, execution evidence, and replay/contract tests.
- Core engine: deterministic state machine, GitHub IO, findings normalization,
  multi-agent lease management, session persistence, loop safety, final gate,
  audit artifacts, telemetry import ledgers, fingerprint ledgers, coverage
  calculation, and public-safe efficiency reports.
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

## Development Workflow And Quality Gates

All non-trivial changes MUST begin by reading the smallest governing contract:
the relevant tests, `README.md`, `skill/SKILL.md`, or this constitution.
Feature specs MUST identify whether they affect the public CLI, the packaged
skill payload, agent-facing instructions, session state, GitHub side effects,
findings intake, telemetry, or final-gate behavior.

Implementation plans MUST include a Constitution Check covering:

- control-plane ownership of state and side effects
- first-principles runtime-kernel modeling, including event inputs, projections,
  policy/action maps, command planning, outbox execution, and replay evidence
- public CLI and machine summary compatibility (including Status-to-Action Map)
- evidence requirements for reply, resolve, and final-gate behavior
- packaged skill boundary and path discipline (Policy Layer vs implementation)
- external intake replaceability and findings normalization
- telemetry attribution, coverage labels, privacy filtering, and fail-open scope
- artifact truth boundaries and non-self-referential telemetry/reporting design
- architecture plateau discipline when feedback would add more edge branches
- test coverage for changed contracts
- agent protocol and lease compatibility (if multi-agent or action-oriented)

Code changes MUST run the smallest verification that matches the scope. Public
CLI or packaging changes MUST include CLI smoke tests. Session, loop, reply,
resolve, or final-gate changes MUST include behavior tests. Documentation-only
changes MUST still be checked for repo-root versus skill-root path correctness
and public contract consistency.
Telemetry changes MUST include tests for safety filtering, deterministic
fingerprints, duplicate or overlapping import behavior, coverage labels, report
artifacts, final-gate/audit integration, and the fail-loud telemetry-command
versus fail-open core-workflow boundary.
Runtime-kernel changes MUST include replay or contract tests that prove the
event inputs, projections, policy decisions, side-effect plans, artifact
boundaries, and final-gate outcomes agree.

## Governance

This constitution governs architecture and product-contract decisions for this
repository. It complements `AGENTS.md`, which governs day-to-day agent behavior
inside the source repository. When this constitution conflicts with lower-level
templates, examples, or reference prose, the lower-level artifact MUST be
updated rather than silently blended.

Amendments MUST include:

- the reason for the change
- the version bump rationale
- affected principles or sections
- dependent templates or runtime guidance reviewed
- verification performed

Versioning follows semantic versioning:

- MAJOR: incompatible governance changes, removed principles, or redefined
  public architecture boundaries
- MINOR: new principles, new sections, or materially expanded governance
- PATCH: clarifications, wording improvements, typo fixes, or non-semantic
  refinements

Every implementation plan, task set, and completion claim MUST review
constitution compliance. A feature that violates a principle MUST document the
violation, why it is necessary, and the simpler compliant alternative that was
rejected.

**Version**: 1.5.1 | **Ratified**: 2026-04-24 | **Last Amended**: 2026-06-21
