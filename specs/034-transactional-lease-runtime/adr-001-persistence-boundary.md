# ADR-001: Use SQLite as the Canonical PR-Session Runtime Store

**Status:** Accepted and implemented
**Date:** 2026-09-24
**Deciders:** Repository maintainer
**Supersedes:** The implicit multi-file persistence design in which
`session.json` is authoritative and `evidence.jsonl` is appended independently

## Context

The current runtime loads `session.json` into memory, mutates it, writes a new
file with `os.replace`, and appends evidence to a separate JSONL file. Atomic
replacement prevents torn JSON but does not serialize two processes that read
the same prior revision. The JSON replacement and JSONL append are also not one
commit. The orchestrator then adds a shadow lease persisted in
`orchestration.json` and loaded into memory, with a different conflict key and
lifecycle.

The required boundary must provide:

- one cross-process writer decision per PR session;
- atomic state + event + outbox commit;
- crash recovery without guessing which file is newer;
- explicit revision and acquisition provenance;
- deterministic replay and fault injection;
- no daemon or external service; and
- a compatible migration path for existing local sessions.

## Decision

Use one SQLite database in each PR workspace as the only authoritative runtime
store. Use short `BEGIN IMMEDIATE` write transactions so a writer acquires its
reservation before reading transition inputs. Keep the transaction free of
network, agent, and slow filesystem effects.

The transaction atomically commits:

1. the expected and next session revision;
2. item and lease state;
3. immutable evidence events; and
4. durable outbox command intents.

`session.json` and `evidence.jsonl` remain supported, versioned compatibility
projections generated after commit. They are not read as authoritative input
after migration. Projection failure marks a database-owned materialization as
dirty and is repaired on the next command; it cannot roll back or falsify the
canonical commit.

Use SQLite's stdlib driver and rollback-journal durability for the first phase.
WAL is not required by the product's low-volume, short-write workload and brings
extra persistent files plus a same-host/shared-memory constraint. A later change
may adopt WAL only with measured reader/writer contention and a versioned backup/
copy contract. Configure foreign keys, an explicit bounded busy timeout, and the
durability mode selected by executable startup tests; do not silently inherit
ambient connection defaults.

SQLite documents that a transaction appears entirely committed or not committed
across program, OS, and power failure, and that separate connections observe
complete committed transactions. It serializes writes, which matches the desired
claim semantics for this local, low-write-concurrency control plane:

- https://www.sqlite.org/atomiccommit.html
- https://www.sqlite.org/isolation.html
- https://www.sqlite.org/whentouse.html

## Options Considered

| Candidate | Current runtime fit | Migration cost | Concurrency semantics | Crash recovery | Testability | Compatibility |
|---|---|---|---|---|---|---|
| File lock + CAS | Small local change | Low | Serializes cooperating writers only | Does not join JSON and JSONL | Race tests are simple; crash proof remains incomplete | Preserves files but not the required invariant |
| File lock + custom journal | Adds a new persistence engine beside current files | Medium | Serializable if every writer adopts the lock | Project-owned roll-forward protocol | Requires a bespoke crash/VFS-style matrix | Preserves shapes but adds a third truth format |
| SQLite (selected) | Matches per-PR local state and short writes | High one-time | Serializable single writer with bounded wait | Native journal recovery | Deterministic transactions plus child-process kill tests | Requires a versioned authority/migration change |
| Daemon/client-server store | Exceeds local-first runtime needs | Very high | Strong centralized coordination | Mature | Adds service integration/failure tests | Adds installation and availability contracts |

### Option A: File lock + revision/CAS only

| Dimension | Assessment |
|---|---|
| Runtime fit | Good for one-file serialization |
| Cross-process claim | Solvable with an advisory lock |
| State + ledger atomicity | Not solved |
| Crash recovery | Still ambiguous between two files |
| Migration cost | Low initially |
| Long-term state space | Grows when journaling/outbox are added |

**Rejected:** It fixes the first race but not the umbrella problem. Adding a
custom prepare journal, commit marker, deduplication, recovery, and outbox would
reimplement a transaction engine while preserving multiple truth surfaces.

### Option B: File lock + custom write-ahead transaction journal

| Dimension | Assessment |
|---|---|
| Runtime fit | Possible on supported local Unix filesystems |
| Cross-process claim | Solved |
| State + ledger atomicity | Emulated by roll-forward recovery |
| Crash recovery | Must be designed and crash-tested locally |
| Migration cost | Medium |
| Long-term state space | Highest; journal becomes a third authoritative format |

**Rejected:** This adds the exact custom recovery state machine the architecture
task is meant to remove. Correctness would depend on fsync ordering, directory
durability, idempotent JSONL repair, and platform locking behavior maintained by
this project.

### Option C: SQLite transaction (selected)

| Dimension | Assessment |
|---|---|
| Runtime fit | Strong for local, per-PR, low-volume state |
| Cross-process claim | Serialized by database write transactions |
| State + ledger atomicity | Native single-database transaction |
| Crash recovery | Native journal recovery plus project fault tests |
| Migration cost | Highest one-time contract change |
| Long-term state space | Lowest once JSON/JSONL become projections |

**Selected:** It is the only candidate that solves all three workflows with one
owner and one commit boundary without adding a daemon or bespoke WAL.

### Option D: Client/server database or coordinator daemon

| Dimension | Assessment |
|---|---|
| Runtime fit | Poor for local-first CLI |
| Cross-process claim | Solved |
| State + ledger atomicity | Solved |
| Crash recovery | Mature |
| Migration/operations cost | Disproportionately high |
| Long-term state space | Adds service lifecycle and availability states |

**Rejected:** Current scale is one machine, one PR workspace, and short mutations.
A daemon or remote service expands the protected baseline without evidence that
SQLite's single-writer model is insufficient.

## Transaction and Commit Semantics

1. Open and validate the schema and local-filesystem precondition.
2. `BEGIN IMMEDIATE` with a bounded busy timeout.
3. Load the current canonical revision and transition inputs inside the
   transaction.
4. Reject an explicit stale expected revision, or evaluate policy against the
   current revision when no revision was supplied.
5. Apply normalized state changes.
6. Insert immutable evidence events and outbox intents with unique identities.
7. Increment the session revision exactly once and commit.
8. After commit, materialize compatibility artifacts for that revision.
9. Execute outbox work outside the transaction; record each result in a new
   transaction before it becomes evidence.

The database commit is the only state commit point. Artifact replacement and
external calls are never inside the write transaction.

## Migration and Compatibility

- A workspace with no database and a valid legacy session is imported once.
- Import reads both legacy files before starting the database commit, validates
  referential and event identity constraints, then commits schema, state, events,
  migration provenance, and revision 1 together.
- A database marker prevents repeat import. Re-running migration is a read-only
  verification, not a merge.
- Malformed or divergent legacy inputs fail loudly and remain untouched.
- Existing JSON/JSONL paths continue to exist as projections for the compatibility
  period. Any machine-readable field that exposes store/revision metadata is
  additive and versioned.
- Direct external edits to projected files are no longer accepted after migration.
  This behavior change must be documented in README, skill guidance if relevant,
  and executable contract tests before release.
- In-place downgrade is unsupported. Before first import, migration creates and
  verifies an immutable legacy-v1 recovery bundle containing the original session
  and ledger bytes plus their hashes. The release runbook may restore the entire
  stopped PR workspace from that bundle; an older binary must never concurrently
  write beside the database.

## Consequences

### Positive

- One authoritative ownership and evidence boundary.
- Cross-process claims and session/ledger commits share the same primitive.
- Recovery uses a mature transaction engine rather than inference across files.
- A durable outbox can represent unknown external-effect outcomes honestly.
- Orchestrator convergence becomes deletion of duplicate policy, not another sync.

### Negative

- Constitution Principle I and documentation that name `session.json` as truth
  must change before implementation.
- Migration and downgrade behavior become public contracts.
- Tests that mutate JSON files directly must move to store builders or explicitly
  remain legacy-migration fixtures.
- The repository gains schema versioning, integrity checks, and backup/copy rules.

### Risks and Mitigations

- **Long writer transaction**: forbid network and artifact IO inside transactions;
  test transaction duration buckets.
- **Lock starvation**: bounded timeout and retryable stable reason; no busy loop.
- **Network filesystem semantics**: preflight rejection; local filesystem only.
- **Projection mistaken for truth**: revision stamp, documentation, and tests that
  edit a projection and prove runtime state does not change.
- **Telemetry self-reference**: emit transaction observations after outcome; the
  telemetry write cannot participate in or amend commit truth.

## Approval Record

Amend Constitution Principle I from the file-specific owner `session.json` to a
versioned runtime store owned by deterministic code, while keeping artifacts as
non-authoritative projections. PR #287 fulfilled this gate with Constitution
2.2.0. The approved design was implemented incrementally by Phase A in PR #288,
Phase B in PR #290, and Phase C in PR #292.
