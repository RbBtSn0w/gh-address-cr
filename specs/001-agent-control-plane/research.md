# Research: Agent Control Plane

## Decision: Physically Separate Runtime From Packaged Skill

Use `src/gh_address_cr/` as the runtime package boundary. Keep
`gh-address-cr/scripts/cli.py` only as a compatibility shim that delegates to
the installed runtime or fails loudly.

**Rationale**: The control plane is now a real product runtime, not skill-owned
workflow glue. Physical separation lets the CLI be installed, tested, versioned,
and reused independently while the packaged skill remains a thin AI-agent
adapter.

**Alternatives considered**:

- In-payload `gh-address-cr/gh_address_cr`: preserves self-contained skill
  installation, but keeps the runtime coupled to the skill payload and delays
  the architecture goal.
- Keep all logic in `scripts/`: lowest migration cost, but it preserves the
  current script-sprawl problem and weakens testability.

## Decision: Deterministic Coordinator With Item-Scoped Claim Leases

Use the CLI control plane as the coordinator. It grants one active
`ClaimLease` per work item and rejects stale, duplicate, or cross-role
submissions.

**Rationale**: Multi-agent work needs parallelism without shared-state drift.
Leases provide bounded ownership and make interruption recovery explicit.

**Alternatives considered**:

- Let agents coordinate through prompts: too fragile and not auditable.
- One global session lock: safe but prevents useful parallelism across
  independent review items.

## Decision: Serialize GitHub Side Effects Through The CLI

Agents never post replies or resolve threads directly. They return evidence;
the CLI validates it, posts replies, resolves threads, and records durable
reply evidence.

**Rationale**: GitHub writes are irreversible enough to require deterministic
ordering, idempotency checks, and audit records.

**Alternatives considered**:

- Let fixer agents call `gh` directly: faster in happy paths, but creates
  duplicate side effects and missing evidence risks.
- Allow verifier agents to resolve after tests pass: still splits a single
  side-effect contract across multiple owners.

## Decision: Versioned JSON-Compatible Agent Protocol

Define `ActionRequest`, `ActionResponse`, `ClaimLease`, `AgentRole`, and
`CapabilityManifest` as JSON-compatible dictionaries with a `schema_version`
field. Validate with Python standard-library code in Phase 1.

**Rationale**: JSON is easy for agents, adapters, tests, and CLI commands to
exchange. Avoiding a new runtime dependency keeps the packaged skill small.

**Alternatives considered**:

- JSON Schema dependency: stronger validation vocabulary, but adds packaging
  and runtime dependency questions.
- Markdown blocks: readable, but weaker for machine validation and parallel
  agent coordination.

## Decision: Promote New Protocol Commands As Advanced/Internal First

Add protocol-oriented commands behind the root runtime CLI only after tests
define their behavior. Keep `review` as the default public path.

**Rationale**: The public contract is already documented around `review`.
Advanced/internal commands let implementation evolve without immediately
forcing a public compatibility promise.

**Alternatives considered**:

- Replace `review` with an agent-specific command: violates current public
  entrypoint discipline.
- Add many public commands immediately: increases support surface before the
  protocol has enough real-world evidence.

## Decision: Multi-Agent Roles Are Capabilities, Not Hardcoded Model Names

Represent coordinator, review producer, triage, fixer, verifier, publisher,
and gatekeeper as roles/capabilities. A single AI agent may perform several
roles in small runs; multiple agents may split roles in larger runs.

**Rationale**: The architecture must support Codex, Claude, local tools, and
future runners without binding to any one provider or skill name.

**Alternatives considered**:

- One command per vendor: creates provider lock-in and documentation drift.
- One agent per role always: clean but overkill for small PRs.

## Decision: Final Gate Preserves Current Reply-Evidence Semantics

The separated runtime must keep final-gate broader than "no unresolved
threads". It must check unresolved GitHub review threads, current-login pending
reviews, session blocking items, terminal thread reply evidence, and required
validation evidence.

**Rationale**: The current product contract already treats zero unresolved
threads as insufficient. Physical runtime separation must not regress the
completion proof.

**Alternatives considered**:

- Gate only on GitHub unresolved thread count: simpler, but permits false
  completion when reply evidence or pending review state is missing.
- Let agents summarize completion evidence: not deterministic enough for a
  control plane.

## Decision: Use Conflict Keys For Parallel Work Safety

Each work item and active lease may carry conflict keys such as file paths,
remote thread ids, or side-effect targets. Parallel mutating leases are allowed
only when conflict keys do not overlap.

**Rationale**: Distinct item IDs alone are not enough. Two different review
items may target the same file or same remote side effect.

**Alternatives considered**:

- One active fixer globally: safest, but loses useful multi-agent parallelism.
- Let agents coordinate file ownership in prose: not enforceable or auditable.

## Decision: Treat GitHub Transient Failures As Evidence-Carrying Blocks

Rate limits and transient GitHub failures use bounded retry. When retry budget
is exhausted, the item becomes blocked with evidence and idempotency data rather
than repeating side effects blindly.

**Rationale**: GitHub writes must be deterministic. Retrying without recorded
idempotency can duplicate replies or obscure partial success.

**Alternatives considered**:

- Immediate failure on the first transient error: too brittle for real PR
  workflows.
- Unbounded retry: risks hung sessions and duplicated side effects.
