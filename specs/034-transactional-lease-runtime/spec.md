# Feature Specification: Transactional Lease Runtime and Persistence Boundary

**Feature Branch**: `feat/034-transactional-lease-runtime`
**Created**: 2026-09-24
**Status**: Superseded in part by
[Spec 035](../035-runtime-store-hardening/spec.md) — Phases A/B/C landed on
`develop` through PRs #287, #288, #290, and #292, but the post-merge audit found
FR-007, FR-008, FR-009, FR-014, SC-002, and SC-003 not fully met (see
[035 validation](../035-runtime-store-hardening/validation.md))
**Input**: The explicit follow-up boundary in Spec 033 / PR #285: cross-process
atomic claim, `session.json` / evidence-ledger crash consistency, and core/shadow
lease convergence.

## Why this is one architecture task

Spec 033 proves the sequential lease transition table and composition-level
rollback ownership. It deliberately does not prove that two processes cannot
claim from the same session revision, that session state and evidence events
survive a crash as one commit, or that the orchestrator's shadow conflict policy
cannot disagree with the core lease policy.

Those are not three unrelated defects. In each case, the runtime currently lacks
one authoritative transaction that answers all of these questions together:

1. what ownership state was observed;
2. whether a transition is allowed;
3. which canonical rows and events commit with it;
4. which external side effects are planned but not yet proven; and
5. which derived artifacts or volatile orchestration views may be rebuilt.

This specification defines that boundary once. It must not be implemented as
three locks, fallback paths, or dual-write repair branches.

## User Scenarios & Testing

### User Story A — Only one process wins a claim (Priority: P1)

As two local agent processes racing on one PR session, exactly one process must
commit a conflicting lease and item claim marker. The loser must observe the
winner's committed revision and receive the existing deterministic conflict.

**Independent Test**: Start two processes behind a barrier, have both claim the
same item or overlapping conflict keys, then assert one committed lease, one
`lease_created` event, one incremented session revision, and one conflict result.

**Acceptance Scenarios**:

1. **Given** two writers that observed revision N, **When** both attempt the same
   claim, **Then** only one transaction commits revision N+1.
2. **Given** a writer waiting behind another writer, **When** it enters its write
   transaction, **Then** policy is evaluated from the newly committed state, not
   from a stale in-memory session.
3. **Given** a bounded lock wait expires, **When** no transaction was committed,
   **Then** the command fails loudly with a stable retryable reason and creates no
   lease, event, projection, or outbox row.

### User Story B — A crash cannot split runtime truth from its ledger (Priority: P1)

As an operator resuming after process termination, I need session state, evidence
events, and planned side effects to describe one committed history, rather than a
session transition with no event or an event for a transition that never committed.

**Independent Test**: Kill a child process at every named commit/materialization/
execution checkpoint, reopen the store, and prove the runtime sees either the old
revision or the complete new revision. Rebuilding compatibility artifacts must
produce the same bytes for the same committed revision.

**Acceptance Scenarios**:

1. **Given** a crash before database commit, **When** the store reopens, **Then**
   none of that transition's state, event, or outbox intent is visible.
2. **Given** a crash after database commit but before `session.json` or
   `evidence.jsonl` materialization, **When** recovery runs, **Then** canonical
   runtime truth is already complete and the projections are rebuilt.
3. **Given** a crash after an external GitHub request begins but before its result
   is recorded, **When** recovery runs, **Then** the outbox row is `unknown`, no
   success evidence is invented, and idempotent reconciliation is required.

### User Story C — The orchestrator projects, but never owns, a second lease (Priority: P2)

As an orchestrator, I need worker dispatch to use the core runtime's committed
lease and conflict policy, so an in-memory shadow cannot reject, outlive, expire,
or contradict canonical ownership.

**Independent Test**: Claim two non-overlapping hunks in one file through the
orchestrated flow, restart the orchestrator, and verify dispatch state is rebuilt
from canonical leases without a second grant or a second conflict decision.

**Acceptance Scenarios**:

1. **Given** a committed core lease, **When** a worker is dispatched, **Then** the
   volatile dispatch record references that `lease_id` and revision and performs
   no independent lease grant.
2. **Given** the orchestrator restarts, **When** it reconciles, **Then** active
   dispatches are derived from committed runtime state and resumable requests.
3. **Given** a canonical lease expires or is released, **When** a worker submits,
   **Then** the runtime rejects it from canonical policy even if a stale dispatch
   token remains in memory.

## Requirements

### Functional Requirements

- **FR-001 (single owner)**: One per-PR SQLite database MUST be the only
  authoritative owner of session metadata, items, leases, evidence events,
  transaction revisions, and side-effect outbox state after migration.
- **FR-002 (atomic transition)**: A runtime transition MUST evaluate policy and
  commit state rows, evidence events, and outbox intents in one SQLite write
  transaction. No caller may persist one member of that set independently.
- **FR-003 (serialized claims)**: Claim transactions MUST acquire the write
  transaction before loading policy inputs. Cross-process claims MUST serialize;
  stale in-memory session dictionaries are not valid claim inputs.
- **FR-004 (explicit provenance)**: A claim result MUST distinguish `created`
  from `reentered`. Rollback ownership MUST derive from committed provenance, not
  from comparing a pre-call list of lease identifiers.
- **FR-005 (one claim marker)**: Item claim state MUST be projected from the
  canonical active lease relationship. A separately mutable item claim marker
  MUST NOT remain a second source of truth.
- **FR-006 (durable events)**: Evidence event identity MUST remain stable and
  unique. State and its transition event commit together; replay MUST not append
  duplicates.
- **FR-007 (outbox truth)**: External and filesystem side effects MUST be planned
  as durable outbox commands. A plan is not completion evidence. Only a recorded
  execution result may advance evidence-dependent policy.
- **FR-008 (compatibility projections)**: `session.json` and `evidence.jsonl`
  become versioned, rebuildable compatibility projections. Their headers or
  adjacent metadata MUST identify the canonical database revision. The runtime
  MUST NOT read them as truth after migration.
- **FR-009 (migration)**: First open MUST import a valid legacy session and ledger
  exactly once under an exclusive transaction, preserve record identifiers and
  public values, and fail loudly on malformed or contradictory input. It MUST NOT
  silently choose between divergent sources.
- **FR-010 (no dual-primary period)**: There MUST be no supported mode in which
  SQLite and JSON/JSONL are both accepted as authoritative writers.
- **FR-010a (downgrade boundary)**: In-place downgrade after migration is not
  supported. Migration MUST retain a verified immutable legacy-v1 recovery bundle;
  rollback requires a stopped-workspace restore and MUST reject concurrent older
  writers.
- **FR-011 (shadow convergence)**: The orchestrator may retain a volatile worker
  dispatch registry, but it MUST not own lease TTL, status, conflict keys, or
  release policy. Those decisions belong only to the runtime transaction.
- **FR-012 (public compatibility)**: Existing CLI commands, reason codes, exit
  codes, ActionRequest/ActionResponse fields, and final-gate truth remain stable
  unless an additive versioned contract in a phase explicitly changes them.
- **FR-013 (local filesystem)**: The canonical database MUST be on the same local
  machine as all participating processes. Unsupported network filesystems MUST
  fail preflight rather than weaken locking or durability semantics.
- **FR-014 (bounded contention)**: Lock contention MUST use a documented bounded
  wait and stable retry outcome. The runtime MUST NOT spin indefinitely or fall
  back to unlocked writes.
- **FR-015 (telemetry)**: Each transaction attempt MUST emit bounded events for
  operation category, outcome, contention bucket, recovery action, schema version,
  and migration outcome. Telemetry MUST exclude repo names, paths, item IDs,
  lease IDs, SQL, payloads, agent IDs, and database contents.
- **FR-016 (fail-open telemetry)**: Telemetry export failure MUST not alter commit
  or recovery truth. Persistence failure MUST fail closed for the affected runtime
  mutation.

### Constitution Alignment

- **Control Plane Impact**: This changes the authoritative state owner from the
  specifically named `session.json` to a per-PR SQLite store. A Constitution
  Principle I amendment is mandatory before implementation.
- **Runtime Kernel Model**: Typed transition inputs are reduced under one current
  revision into canonical state, evidence events, and outbox commands. Policy is
  the Spec 033 table plus the transaction/recovery tables in this spec.
- **CLI / Agent Contract Impact**: Phase A is intended to preserve commands and
  output. Additive diagnostic fields such as persistence schema/revision require
  a versioned machine contract before exposure.
- **Evidence Requirements**: Database events are canonical evidence. Exported
  JSONL is a projection and cannot satisfy a gate if it is newer than no known
  database revision or has been edited externally.
- **Packaged Skill Boundary**: Persistence implementation and contracts live in
  repo-root `src/`, `specs/`, and `tests/`. `skill/` changes only if recovery or
  status-to-action guidance changes.
- **External Intake Replaceability**: Normalized findings remain unchanged and
  are transaction inputs, not a persistence backend.
- **Telemetry Evidence Boundary**: Transaction telemetry is observed evidence,
  never commit truth. The reporting write itself is outside measured business
  counts and cannot make a transaction pass.
- **Architecture Plateau Risk**: SQLite replaces competing file mutations and
  the shadow ownership policy. Hidden fallbacks, extra ownership flags, and
  artifact-backed repair are prohibited.
- **Fail-Fast Behavior**: Unsupported schema versions, corrupt legacy artifacts,
  divergent migration inputs, network filesystems, integrity-check failures, and
  lock timeout all fail with explicit diagnostics.

### Key Entities

- **Runtime Store**: One SQLite database per PR workspace, with schema version,
  migration state, and the latest committed revision.
- **Runtime Transaction**: One policy evaluation and atomic commit identified by
  transaction ID, expected revision, operation category, and outcome.
- **Session Projection**: The current session metadata and item collection derived
  from canonical normalized rows.
- **Lease**: Canonical item ownership with status, role, holder, conflict keys,
  request binding, expiry, and acquisition provenance.
- **Evidence Event**: Immutable, uniquely identified event committed with the
  transition it describes.
- **Outbox Command**: Durable plan for an effect with an idempotency key and
  `planned`, `in_flight`, `succeeded`, `failed`, or `unknown` execution state.
- **Compatibility Artifact**: Rebuildable `session.json` or `evidence.jsonl`
  materialized from one committed database revision.
- **Worker Dispatch Projection**: Volatile orchestrator routing data referencing
  a canonical lease; it is not ownership state.

## Success Criteria

- **SC-001**: A repeated 100-process barrier race on one item produces exactly one
  active lease and one creation event per run, with no lost committed revision.
- **SC-002**: Fault injection at every named transaction and projection checkpoint
  always reopens to the old or complete new revision, never a mixed canonical state.
- **SC-003**: Replaying migration, recovery, or projection materialization is
  idempotent and produces no duplicate evidence or outbox commands.
- **SC-004**: The orchestrator has zero independent lease-conflict, TTL, terminal
  status, or force-release decisions after Phase C.
- **SC-005**: Existing unstacked and stacked PR-session contract suites pass with
  unchanged completion truth and no hidden fallback to legacy artifacts.
- **SC-006**: Telemetry privacy tests prove no repository identity, filesystem
  path, item/lease/request identifiers, SQL, payload, or agent identity is exported.

## Scope Boundaries

- No remote or multi-host database service.
- No change to GitHub stack ownership or merge side effects.
- No attempt to make a remote GitHub mutation and its local transaction one ACID
  transaction; the durable outbox and reconciliation model owns that boundary.
- No general event-sourcing rewrite. Current state uses normalized canonical rows;
  immutable evidence events support audit and replay of decisions where required.
- No automatic implementation before the Constitution amendment and persistence
  contract are approved.
