<!--
Sync Impact Report
Version change: 1.0.1 -> 1.1.0
Amendment reason:
- Solidify the "Agent Control Plane" architecture: physically separated runtime, structured agent protocol, and multi-agent coordination.
Version bump rationale:
- MINOR: Added Principle VI (Multi-Agent Coordination) and materially expanded Principle II (Agent Protocol) and IV (Runtime Separation).
Modified principles:
- II. CLI Is The Stable Public Interface (expanded with Structured Agent Protocol)
- IV. Packaged Skill Boundary Is Explicit (expanded with Physical Separation of Runtime)
Added sections:
- Principle VI. Multi-Agent Coordination and Claim Leases
Removed sections:
- None
Templates requiring updates:
- .specify/templates/plan-template.md: ✅ updated (concepts aligned)
- .specify/templates/spec-template.md: ✅ updated (concepts aligned)
- .specify/templates/tasks-template.md: ✅ updated (concepts aligned)
- .specify/templates/checklist-template.md: ✅ updated (concepts aligned)
Runtime guidance requiring updates:
- AGENTS.md: ✅ updated (separation and protocol rules aligned)
- README.md: ✅ updated (architecture overview aligned)
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

Rationale: PR review handling has external side effects and resumable state.
The workflow must be auditable after interruptions and reproducible without
depending on an agent's conversational memory.

### II. CLI Is The Stable Public Interface

High-level CLI commands are the only agent-safe public surface. The interaction
between the agent and the control plane MUST follow the **Structured Agent Protocol**,
using formal `ActionRequest` and `ActionResponse` schemas. The main public
entrypoint is `review`; advanced entrypoints such as `threads`, `findings`,
`adapter`, and `review-to-findings` MAY exist for explicit integrations but
MUST NOT replace `review` as the default orchestration path. Machine-readable
outputs, reason codes, wait states, exit codes, cache artifacts, and stable
input contracts MUST be preserved or versioned when changed.

Rationale: AI agents, humans, CI, and future agent runners need the same stable
control boundary. Formal protocols separate cognitive reasoning from side-effect
execution.

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
payload under `gh-address-cr/`. The **Deterministic Runtime** MUST be physically
separated from the packaged skill adapter. The skill adapter MUST remain a thin
layer that routes to the installed runtime CLI and interprets status codes.
Runtime logic MUST NOT be authored or maintained as skill-owned workflow code.

Path language MUST match the active scope. Repo-root docs and commands use
paths such as `gh-address-cr/scripts/cli.py`; skill-owned docs use paths such
as `scripts/cli.py`, `references/...`, and `agents/openai.yaml`.

Rationale: The project ships a skill. Blurring repo-root and skill-root paths
creates broken installed instructions and unstable agent behavior. Physical
separation prevents runtime-logic drift within the skill payload.

### V. Testable Contracts And Fail-Fast Changes

Public behavior changes MUST update code, docs, and executable tests together.
The project MUST fail fast on missing tools, malformed producer output, invalid
handoff formats, unsafe resolve-only handling, and unsupported public command
usage. Silent fallbacks, hidden compatibility shims, alternate prompt contracts,
and narrative-only findings ingestion are forbidden unless they are explicitly
documented, tested, and versioned as public behavior.

Rationale: Agent workflows amplify ambiguity. A weak fallback can create false
completion claims, duplicate side effects, or unrecoverable session drift.

### VI. Multi-Agent Coordination and Claim Leases

The control plane MUST coordinate multi-agent work through explicit, item-scoped
claim leases. No agent or process MAY mutate a work item without an active lease.
The system MUST define specialized roles (coordinator, producer, triage, fixer,
verifier, publisher, gatekeeper) and enforce lease policies (expiry, reclaiming,
conflict detection) to ensure parallel execution is safe and auditable.

Rationale: PR repair is often multi-dimensional. Without explicit ownership,
parallel agents can overwrite each other, resolve without evidence, or claim
completion from stale state.

## Runtime Architecture

The intended architecture is:

- Core engine: deterministic state machine, GitHub IO, findings normalization,
  multi-agent lease management, session persistence, loop safety, final gate,
  audit artifacts, and telemetry.
- CLI: stable public interface for agents, humans, CI, and future automation.
- Agent protocol: structured `ActionRequest` and `ActionResponse` schemas
  for `fix`, `clarify`, `defer`, and `reject` workflows.
- Skill: thin usage adapter that tells an AI agent when to invoke the CLI and
  how to react to machine-readable statuses.
- External producers: replaceable review sources that emit normalized findings
  JSON or fixed `finding` blocks.

The CLI control plane is authoritative. Agent reasoning MAY decide how to fix,
clarify, defer, or reject a specific item, but the CLI MUST own session
transitions, GitHub writes, reply/resolve ordering, and final-gate evaluation.

## Development Workflow And Quality Gates

All non-trivial changes MUST begin by reading the smallest governing contract:
the relevant tests, `README.md`, `gh-address-cr/SKILL.md`, or this constitution.
Feature specs MUST identify whether they affect the public CLI, the packaged
skill payload, agent-facing instructions, session state, GitHub side effects,
findings intake, telemetry, or final-gate behavior.

Implementation plans MUST include a Constitution Check covering:

- control-plane ownership of state and side effects
- public CLI and machine summary compatibility
- evidence requirements for reply, resolve, and final-gate behavior
- packaged skill boundary and path discipline
- test coverage for changed contracts
- agent protocol and lease compatibility (if multi-agent or action-oriented)

Code changes MUST run the smallest verification that matches the scope. Public
CLI or packaging changes MUST include CLI smoke tests. Session, loop, reply,
resolve, or final-gate changes MUST include behavior tests. Documentation-only
changes MUST still be checked for repo-root versus skill-root path correctness
and public contract consistency.

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

**Version**: 1.1.0 | **Ratified**: 2026-04-24 | **Last Amended**: 2026-04-24
