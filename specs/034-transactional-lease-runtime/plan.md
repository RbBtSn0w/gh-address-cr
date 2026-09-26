# Implementation Plan: Transactional Lease Runtime and Persistence Boundary

**Branch**: `feat/034-transactional-lease-runtime` | **Date**: 2026-09-24 |
**Spec**: [spec.md](./spec.md) | **Decision**:
[ADR-001](./adr-001-persistence-boundary.md)

## Summary

Replace load/mutate/atomic-replace plus independent JSONL append with one
per-PR SQLite transaction boundary. The canonical transaction owns session
revision, items, leases, evidence events, and side-effect outbox intents.
Legacy files become rebuildable compatibility projections. The orchestrator
then projects worker dispatch from canonical leases instead of granting a
second lease with independent conflict and TTL policy.

This document is the umbrella architecture and rollout plan. Constitution 2.2.0
now authorizes the versioned persistence boundary; Phase A owns the initial
implementation and must keep B/C behavior out of its branch.

## Current Verified Baseline

- GitHub's repository default branch is `main`.
- PR #285 merged commit `9bdab3006231da2af3dfe2550295088c127e59a9`
  into `develop` on 2026-09-24; `main` at the start of this task was release
  `v3.15.3` (`b7d6d1c`) and did not contain Spec 033.
- This branch therefore starts from `origin/develop` at the PR #285 merge.
- `write_json_atomic` writes a temporary JSON file and replaces `session.json`.
  It has no cross-process revision check or surrounding lock.
- `EvidenceLedger.append` independently appends one JSON line.
- Mutation paths call ledger and session persistence in multiple orders; there
  is no shared commit object.
- Spec 033 FR-009 explicitly limits its claim to sequential transition and
  composition-level rollback correctness.
- The orchestrator persists `active_leases` in `orchestration.json` and loads them
  into memory with its own context-key conflict and TTL behavior. That file is
  subordinate in principle but independently decisive in the current implementation.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: Python stdlib `sqlite3`; existing runtime kernel,
session, lease, evidence-ledger, outbox/side-effect, orchestrator, and OTel code
**Storage**: one versioned SQLite database per PR workspace; JSON/JSONL are
compatibility projections only
**Testing**: `unittest`, multi-process barriers, child-process crash injection,
schema/migration contract fixtures, deterministic replay, and existing PR-session
and final-gate suites
**Target Platform**: local macOS/Linux filesystem; network filesystems unsupported
**Performance Goal**: short write transactions, bounded lock wait, one canonical
revision increment per successful transition; no network IO while holding a write
transaction
**Compatibility**: stable CLI and agent protocol by default; persistence migration
and projection semantics are explicitly versioned public behavior

## Architecture Preflight

### Authoritative state owner

After migration, `runtime.sqlite3` in the PR workspace is the only authoritative
owner of session metadata, items, leases, evidence events, revision, migration
state, artifact materialization state, and outbox commands. GitHub remains
authoritative for remote threads, pending reviews, checks, and side-effect results
that are reobserved from GitHub.

`session.json`, `evidence.jsonl`, `orchestration.json`, reports, completion
summaries, request files, and orchestration audit logs are artifacts. The future
orchestrator active-dispatch registry is a volatile projection; resumable delivery
metadata may still be materialized, but it cannot own lease policy. None can
overwrite canonical state.

### External facts and event inputs

- Current committed session revision and schema version.
- Normalized findings and current GitHub facts already accepted by existing
  contracts.
- A typed transition request: operation, actor/role, item, expected revision,
  request binding, conflict keys, and timestamp.
- Clock input used for lease expiry, supplied explicitly in kernel tests.
- External execution result or reconciled GitHub observation for an outbox command.
- Legacy session and ledger files only during the one-time migration event.
- Process interruption and lock contention as explicit recovery inputs.

### Canonical runtime state and projections

Canonical normalized tables are defined in `data-model.md`. A pure projection
builds the existing session dictionary, claim eligibility, final-gate inputs,
and compatibility artifacts from one committed revision. Item claim status is
derived from its canonical active lease relationship; it is not independently
written as a second owner.

### Deterministic transition and policy tables

- Spec 033 remains the lease status/claim policy source.
- `contracts/transaction-boundary-v1.md` defines transaction outcome, recovery,
  outbox, and artifact materialization tables.
- Claim policy executes after the writer reservation is acquired and facts are
  loaded inside the transaction.
- Recovery uses database state and outbox status, not artifact timestamps.

### Transaction, CAS, and locking boundary

- One database per PR session bounds contention and failure scope.
- `BEGIN IMMEDIATE` obtains the write reservation before policy reads.
- An expected revision, when supplied, is a CAS guard inside the transaction.
- SQLite serializes writers; a bounded busy timeout maps to a stable retryable
  runtime outcome.
- The transaction contains only database reads/writes. No GitHub, agent, report,
  request-file, or compatibility-artifact IO occurs while the write lock is held.

### Side-effect command plan and outbox boundary

Policy inserts a durable outbox command with an idempotency key in the same
transaction as the state that requires it. Execution happens after commit.
Results are recorded in a later transaction. A crash from request start until a
confirmed result yields `unknown`; recovery reconciles with GitHub or retries only
when the operation contract proves idempotency. `planned` and `in_flight` are not
completion evidence.

### Artifact truth and telemetry self-reference

Compatibility artifacts carry their source database revision and are rebuilt
from the database. A dirty or absent artifact cannot invalidate a committed
runtime transition, and an edited artifact cannot create one. Final-gate reads
canonical state plus current GitHub facts.

OTel records the already-decided transaction outcome after commit/rollback. It
never records SQL or identifiers and never participates in state, outbox, gate,
or projection decisions. Artifact/report writes and their telemetry are outside
the transaction's business-event counts.

### Recovery, replay, and idempotency

- SQLite performs journal recovery on open; project startup then checks schema,
  integrity, migration marker, outbox unknowns, and dirty projections.
- Every event has a unique record ID; every outbox command has a unique
  idempotency key; every session transition increments one revision.
- Projection materialization is replace-by-revision and may be replayed.
- Migration is once-only and replay verifies rather than merges. It also creates
  and verifies an immutable legacy-v1 recovery bundle; in-place downgrade is not
  supported.
- Fault tests terminate real child processes at named checkpoints and reopen the
  workspace. Mock exceptions alone are insufficient crash evidence.

### Session persistence semantics

The compatibility `SessionManager.load()` may continue returning a dictionary,
but mutable dictionaries are snapshots, not write handles. All writes go through
an explicit store transaction/repository API. The legacy unconstrained
`save_session(payload)` surface is retired internally in Phase A; unsupported
callers fail tests rather than silently bypassing revision policy.

### Orchestrator ownership model

The runtime transaction grants/releases/expires the only lease. The orchestrator
receives a dispatch receipt referencing `lease_id`, committed revision, request
binding, and an opaque worker-delivery token. Its volatile registry owns delivery,
not item ownership. It performs no independent conflict, TTL, terminal-state, or
force-release decision and reconciles before every major action.

## Persistence Decision

ADR-001 selects SQLite. File lock + CAS is rejected because it cannot atomically
commit the evidence ledger. File lock + a custom journal is rejected because it
adds a third authoritative format and bespoke crash-recovery engine. A daemon or
client/server database is rejected as disproportionate for local, low-volume,
per-PR state.

Initial journal mode is rollback journal, not WAL. The workload needs serialized
short writes more than concurrent long readers, and rollback mode has the simpler
copy/backup boundary. WAL remains a future measured decision, not a fallback.

## Constitution Check

- **Control plane ownership — PASS**: Constitution 2.2.0 requires one versioned
  authoritative store, treats compatibility artifacts as projections, and
  prohibits dual-primary migration.
- **First-principles kernel — PASS**: typed inputs, canonical projection, policy
  tables, transaction/outbox boundary, execution evidence, and replay are explicit.
- **Public CLI — PASS with versioned persistence contract**: no planned command or
  exit change in A; migration/projection behavior is documented and tested.
- **Evidence-first handling — PASS**: state and evidence commit together; external
  success requires recorded result.
- **Packaged skill boundary — PASS**: implementation stays under `src/`; skill
  changes are only agent-facing recovery/compatibility guidance.
- **Telemetry — PASS by design**: bounded transaction events, privacy exclusion,
  and fail-open export are required in every phase.
- **Artifact truth — PASS**: JSON/JSONL/reports are projections, never inputs after
  migration.
- **Complexity budget — PASS if legacy writers are removed**: SQLite adds a schema
  layer but deletes multi-file authority and shadow lease policy. A dual-primary
  bridge would fail this gate.

## Rollout Topology: Native Stack A → B → C

The PR stacking dependency gate is satisfied:

1. B materially depends on A's store, schema, transaction API, and revision.
2. C materially depends on A's canonical lease receipt and B's recovery/outbox
   semantics.
3. B or C must not land on `develop` without their lower layers.
4. Each layer remains an independently reviewable correctness claim.

Use GitHub's native Stack after implementation authorization, not three ordinary
PRs that merely mention an order. Branch names below are proposed; creating,
submitting, rebasing, pushing, or linking them requires separate authorization.

### A — Atomic Store and Cross-Process Claim

**Owning branch**: `feat/034a-atomic-runtime-store`
**Base**: `develop` after the approved Constitution amendment (the amendment may
be the first commit/layer if maintainers require governance review separately)
**Public contract**: persistence-boundary v1; existing CLI behavior preserved;
projection authority changes are documented
**Scope**:

- schema/migration framework and canonical tables;
- one-time legacy import with fail-loud validation;
- explicit transaction/repository API and removal of internal free-form saves;
- atomic claim/re-entry/release/expiry plus state/event commit;
- derived item claim projection and acquisition provenance;
- multi-process race and lock-timeout tests;
- compatibility artifact materialization at committed revision.

**OTel**: root-span events `persistence.transaction` and
`persistence.migration` with bounded operation/outcome/contention/schema fields;
no new child span without separate approval.

**Minimum verification**: focused schema/migration tests, Spec 033 transition
contracts, two-process and 100-process claim race, crash before/after commit,
projection revision tests, privacy tests, and `git diff --check`.

**Completion criteria**: no production lease mutation bypasses the transaction;
exactly one winner under race; legacy import is idempotent; JSON/JSONL cannot
mutate truth; full repository Completion Standard passes.

### B — Crash-Consistent Evidence, Outbox, and Recovery

**Owning branch**: `feat/034b-crash-consistent-outbox`
**Base**: A
**Public contract**: additive versioned outbox/recovery diagnostics and explicit
projection revision metadata; Status-to-Action guidance updated if new recovery
codes are user-visible
**Scope**:

- route every remaining session + evidence mutation through A's transaction;
- durable outbox planning and execution-result recording;
- `unknown` external-effect reconciliation;
- dirty artifact materialization tracking and deterministic repair;
- kill-point crash matrix and replay/idempotency contracts;
- final-gate reads canonical store and current GitHub facts only.

**OTel**: bounded `persistence.recovery`, `outbox.execution`, and
`artifact.materialization` events; no paths, IDs, payloads, or SQL.

**Minimum verification**: child-process kills at every contract checkpoint,
duplicate replay, dangling `in_flight` recovery, projection rebuild, existing
reply/resolve/publish/final-gate behavior tests, privacy tests.

**Completion criteria**: no session transition and evidence event can disagree
after reopen; no outbox plan counts as success; unknown external effects produce
honest recovery; full repository Completion Standard and PR-session `final-gate`
compact evidence pass.

### C — Core/Shadow Lease Convergence

**Owning branch**: `feat/034c-orchestrator-lease-convergence`
**Base**: B
**Public contract**: worker packet/dispatch receipt versioned only if serialized
shape changes; core lease commands and reason codes otherwise preserved
**Scope**:

- replace shadow lease grant with a volatile dispatch projection of the canonical
  lease receipt;
- remove shadow conflict, TTL, terminal state, and force-release policy;
- reconcile dispatch from canonical state before major actions and after restart;
- prove same-file non-overlapping hunk behavior uses only core conflict policy;
- delete obsolete rollback branches that existed only because two grants could
  disagree.

**OTel**: bounded `orchestrator.reconcile` event reporting outcome and count
bucket only; no worker, lease, item, path, or context identity.

**Minimum verification**: orchestrator restart/replay, stale dispatch rejection,
same-file hunk concurrency, lease expiry/release, no-second-grant contract, and
all existing orchestrator tests.

**Completion criteria**: an AST/contract inventory finds no independent shadow
lease policy; all worker mutation validates one canonical lease; full repository
Completion Standard and affected PR-session final-gate evidence pass.

## Full Completion Standard Per Layer

Only after the layer's focused tests pass:

1. `pip install -e .`
2. `ruff check src tests scripts/build_plugin_payload.py`
3. `python3 -m unittest discover -s tests`
4. `python3 -m gh_address_cr --help`
5. `python3 -m gh_address_cr agent manifest`
6. `python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr`
7. `python3 scripts/build_plugin_payload.py --check`
8. For PR-session handling, run `final-gate` and retain its compact completion
   line with telemetry coverage and report artifacts.

## Implementation Gate and Current Status

Constitution 2.2.0 and the persistence-boundary v1 contract are approved. Phase A
is complete locally on its owning branch: claims serialize under the writer
reservation, compatibility artifacts are projection-only, and the complete
repository Completion Standard passes. No file-lock shim, SQLite/JSON
dual-primary mode, or hidden fallback is permitted.
