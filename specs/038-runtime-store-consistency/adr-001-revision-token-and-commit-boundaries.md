# ADR-001: Revision Tokens Advance Only Across Contiguous Commits

**Status:** Accepted
**Date:** 2026-10-01
**Deciders:** Repository architecture owner

## Context

The 3.16.0 release review (`origin/main...origin/develop`, PR #289) verified 15
defects in the transactional runtime introduced by Specs 033–037. Each was
reproduced against `develop@bad0bd9` with a throwaway probe. The defects share a
small number of root causes:

| Root cause | Findings |
|---|---|
| A revision token is forwarded without the payload it describes | publisher lost update (side_effect_outbox `_update_revision`), `_begin_attempt` two-transaction split |
| Evidence is appended to a session dict after its transaction committed | `request_issued` dropped on fresh claim; `classification_recorded` + `request_issued` dropped on batch claim |
| A projection is read back as truth | `SessionEvidenceLedger.load` reads `evidence.jsonl`, restoring classifications from it |
| Decisions made outside the write lock are not re-checked inside it | `recover()` demotes a live command; claim replaces committed metadata with a pre-lock copy |
| Error mapping is incomplete at new persistence boundaries | raw `sqlite3.OperationalError` escapes; `_validate_schema` maps busy to invalid; gate treats every `SessionError` as "no session"; final-gate reports `STALE_REVISION` as non-retryable |
| Authority is granted before it is earned | an uncommitted migration's recovery bundle blocks every retry |
| Version and shape contracts at boundaries | dev previews fail the runtime minimum; protocol 1.0 still silently accepted; naive lease timestamps; batch re-entry keeps a stale request hash; out-of-order lifecycle item crashes metrics; final-gate archives a live SQLite file |

The most severe one breaks the property the transactional runtime exists to
provide. `mark_outbox_in_flight` and `record_outbox_result` commit at
`latest + 1` with no expected revision and return `self.load()`.
`_update_revision` then copies only the new revision onto the publisher's
in-memory session, which still holds the payload loaded before the GitHub call.
The publisher's final whole-session `save_session` passes its compare-and-swap,
and `_write_leases` deletes a lease that another agent committed in the meantime.

## Decision

### D1 — Contiguous-token rule

> An outbox-only commit (`plan`, `in_flight`, `result`, `recover`) records the
> external fact unconditionally. It may advance a caller's revision token only
> when that token equals the commit's base revision.

- Store outbox methods return an `OutboxCommit(base_revision, revision)` instead
  of reloading the whole snapshot.
- `side_effect_outbox` advances the session token only when
  `session.revision == base_revision`. Otherwise the token stays stale, and the
  caller's next whole-session save fails with the documented, retryable
  `STALE_REVISION`.
- Recording a plan or result never takes `expected_revision`. A real GitHub
  mutation must never go unrecorded because of a concurrent unrelated commit.
- The `in_flight` attempt evidence commits in the same transaction as the
  `in_flight` transition, which removes the two-transaction split.
- `recover()` keeps its own revision bump, but callers that hold a token
  re-check it the same way. `side_effect_state` therefore advances the caller
  only across a contiguous recovery commit.

### D2 — Publish is replayable, so stale publishes rerun

`publish_github_thread_responses` is idempotent through the outbox. A replay
reuses every `succeeded` command and performs zero new GitHub mutations. The
CLI publish entry is therefore wrapped in `retry_on_stale_revision`, and that
function's contract is widened explicitly from "pure before the save" to
"pure, or idempotent through the canonical outbox". A contract test counts
`post_reply` and `resolve_thread` calls across the replay and expects no new
mutations.

### D3 — Evidence commits with the state it describes

Every ledger append happens inside the transaction mutation, on the dict the
transaction owns (`current`), or is passed through `evidence=`.

- A fresh claim commits `request_issued` together with the lease.
- A batch claim commits `classification_recorded` and `request_issued` inside
  `commit_batch`.
- The meaning of `request_issued` changes from "request file written" to
  "request issuance committed". The request file is a rebuildable artifact:
  re-entry rebuilds a missing or outdated file and records a second
  `request_issued` with `rebuilt: true`.

### D4 — Projections are never input

`SessionEvidenceLedger.load` returns the canonical `evidence_events` rows plus
the session's own pending buffer. It never reads `evidence.jsonl`.

### D5 — Re-check decisions under the lock

- `recover()` captures `(command_id, owner_token)` at read time and demotes
  each row only `WHERE status = 'in_flight' AND owner_token IS ?`. It also
  clears `in_flight_since`.
- A claim captures the metadata base right after load. It then applies only
  the keys its own stack-context refresh changed, rather than replacing the
  whole metadata object.

### D6 — Complete error mapping at persistence boundaries

- Store public methods translate SQLite busy errors to `PersistenceBusyError`,
  and `_validate_schema` checks `_is_busy` before mapping `DatabaseError` to
  `PERSISTENCE_INVALID`.
- `Gatekeeper.run` creates a session only for `SESSION_NOT_FOUND` and
  re-raises every other `SessionError`.
- `final-gate` emits `SessionError` through `output_session_error`, keeping the
  reason code and `retryable`, and reruns its evaluation on `STALE_REVISION`.
  Its GitHub calls are read-only.

### D7 — Authority only after commit

While the store is uninitialized, a complete recovery bundle has no authority:
no committed migration ever verified against it. A self-consistent bundle of
*different* legacy inputs is renamed aside (`*.superseded-<stamp>`), never
deleted, and rebuilt. A bundle whose files fail their own manifest is still
tampering and fails fast (Spec 035 contract unchanged). Legacy item and lease
shapes are validated before any bundle is written, so malformed input fails
with `PERSISTENCE_INVALID` instead of `AttributeError`.

### D8 — Boundary contracts

- **Runtime minimum:** runtime compatibility compares the *release segment* of
  the runtime version with the minimum, so `3.16.0.dev303+abc` satisfies
  `3.16.0` and `3.15.9` does not. Staging builds (`0.0.0.devN`) remain
  incompatible by design; they are packaging probes, not skill runtimes.
- **ActionRequest protocol:** an `ActionRequest` whose `schema_version` is not
  in `SUPPORTED_PROTOCOL_VERSIONS` fails fast at submit with
  `PROTOCOL_VERSION_INCOMPATIBLE`. Re-entry (single and batch) rebuilds such a
  request at the current protocol and recomputes the lease hash, which is the
  upgrade path for leases issued by 3.15.x. `ActionResponse.schema_version`
  remains an echo of its request and is not independently versioned.
- **Lease timestamps:** naive lease timestamps are interpreted as UTC by the
  store's coercer.
- **Lifecycle metrics:** items whose verification precedes addressing are
  excluded as `verified_before_addressed` rather than crashing the report.
- **Archiving:** final-gate takes the store's write reservation, archives
  `runtime.sqlite3` with the SQLite backup API, then removes the workspace. A
  store another command is still writing is left in place and auto-clean is
  skipped instead of racing it.

### D9 — Opportunistic projection repair on read

`load_session` repairs dirty projections only if it can take the write lock
without waiting (`busy_timeout = 0`). Otherwise it defers the repair, emitting
`artifact_recovery/deferred`, and returns the canonical snapshot. Readers never
block for the busy timeout behind a writer.

## Options Considered

### Option A: Contiguous-token rule plus replayable publish (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Low: one rule in one wrapper; store returns a tuple |
| Cost | Small diff; removes three full snapshot decodes per side effect |
| Scalability | Unchanged; a conflict costs one publish replay with no new mutations |
| Team familiarity | Reuses the existing `STALE_REVISION` retry contract |

**Pros:** closes the CAS bypass at its single source; fails toward the
documented retry; needs no new state.
**Cons:** under contention a publish replays its plan, which costs GitHub
reads.

### Option B: Outbox commits never advance the session revision

| Dimension | Assessment |
|---|---|
| Complexity | Medium: evidence rows and materialization assume one revision sequence |
| Cost | Splits the revision sequence into two clocks |
| Scalability | Same as A |
| Team familiarity | New concept |

**Pros:** no token bookkeeping.
**Cons:** evidence rows written by outbox commits would carry a revision that
no session state corresponds to, which breaks projection metadata.

### Option C: Publisher persists per item through `transact_working_set`

| Dimension | Assessment |
|---|---|
| Complexity | High: publisher state is spread across items, leases and evidence |
| Cost | Rewrites the publisher's persistence model |
| Scalability | Best: unrelated concurrent claims never conflict |
| Team familiarity | Matches Spec 036's bounded working-set direction |

**Pros:** the right long-term depth; removes whole-session writes from publish.
**Cons:** too large for a release blocker. **Recorded as follow-up.**

## Architecture Preflight

| Item | Answer |
|---|---|
| Authoritative state owner | `runtime.sqlite3` (`sessions`, `items`, `leases`, `evidence_events`, `outbox_commands`); unchanged |
| External facts / event inputs | GitHub mutation results, recorded as outbox results unconditionally (D1) |
| Projection shape | `session.json`, `evidence.jsonl` and metadata; revision-stamped; repaired opportunistically on read (D9); never input (D4) |
| Decision function | Lease transition table (Spec 033); contiguous-token rule (D1) |
| Side-effect plan / outbox boundary | Outbox rows are planned and transitioned in their own commits; evidence for `in_flight` commits with the transition (D1) |
| Artifact truth boundary | Request files are rebuildable artifacts (D3); recovery bundle authority starts at commit (D7) |
| Telemetry self-reference | New outcomes (`deferred`, `bundle_superseded`, `publish_replay`) go through `_emit_persistence_event` with allow-listed operations |
| Recovery, replay, contract tests | One RED contract test per finding, converted from the review probes; replay test counts GitHub mutations |

## Consequences

- **Easier:**
  - A revision token always describes the payload it travels with.
  - Every ledger event in the store has a matching committed state change.
  - Publish under contention converges by replay.
- **Harder:**
  - The publish entry carries a bounded retry; telemetry must distinguish
    replays from first attempts.
- **Revisit:**
  - Option C (per-item publisher transactions).
  - Snapshot-consistent multi-statement reads (`BEGIN` on read paths).
  - Full-path efficiency: O(N²) publish decode, `lease_events` full rewrite,
    empty-mutation commits.
  - Orchestrator v1 lease token mapping.
  - Windows `fsync` on read-only handles.
  - Lock-file cleanup.
  - Coarse-mtime drift detection.

## Action Items

See [`plan.md`](plan.md) and [`tasks.md`](tasks.md).
