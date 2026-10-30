# Architecture Preflight: Request-time rejection evidence

## Scope and implementation gate

This records the design for the persistence request deferred from issue #365
in RFC 046. The first PR #374 evaluation attempt on 2026-10-30 encountered an
external executor account restriction; it produced no valid comparison. The
user subsequently required removal of fixed-agent binding. RFC 048 replaces
that integration with an explicit external runner boundary; no executor account
or model is an implementation prerequisite for this persistence change.

The scope is the two `REQUEST_REJECTED` outcomes from
`refresh_stack_context_for_request`: `STACK_CONTEXT_INVALID` and
`STACK_CONTEXT_UNAVAILABLE`. Existing classification rejection evidence retains
its current handling. No new command, error framework, database schema, store,
outbox, or review-state flag is needed.

## Ownership and inputs

| Boundary | Decision |
| --- | --- |
| Authoritative owner | The existing PR workspace's `runtime.sqlite3`, specifically `evidence_events`. Neither a JSONL projection nor an OTel export is authoritative. |
| External input | The existing GitHub stack observation and its existing deterministic rejection decision. Persistence must not trigger another GitHub read or write. |
| Typed local observation | A session-scoped `request_rejected` evidence event with payload `schema_version: request-rejection.v1`, the original status, reason code, `waiting_on`, and an allowlisted stack diagnostic. |
| Projection | Existing `evidence.jsonl` and its revision metadata, regenerated from canonical rows. Rejection summaries gain a versioned `rejection_persistence` diagnostic describing this observation's storage outcome. |
| Policy | Record the already-decided rejection, then raise the original error. Never issue a request because diagnostic persistence failed. Never change the rejection's status, reason code, waiting state, remediation, or exit code. |
| Side effects | One existing bounded SQLite working-set transaction plus derived evidence materialization. No lease, classification, item, metadata-cache, request-file, reply, resolve, or GitHub side effect is introduced. |
| Artifact truth | JSONL is readable diagnostic evidence, not a source for runtime transitions. A projection failure does not undo or invalidate a committed canonical event. |
| Recovery | Existing SQLite recovery and evidence materialization apply. Existing archive backup retains canonical evidence. Do not bootstrap a session, import a projection, or restore an archive to make a rejection write succeed. |

## Minimal write and identity

Use `RuntimeStore.transact_working_set(WorkingSetRequest(), ...)` through a
local rejection-persistence helper. Read the current session ID inside that
transaction and append only its evidence buffer. Do not save the stale session
passed into stack refresh: other commands may have committed items, leases or
metadata while the GitHub read was in flight. The empty working set preserves
all unselected canonical rows. A normal revision advance is expected.

Each observed rejection receives one invocation-local UUID evidence record ID.
Any recovery check for that observation uses the same ID. Separate calls,
including identical calls in the same second, remain separate observations;
replaying an identical record retains the store's existing deduplication rule.
This avoids changing the global evidence identity algorithm.

The event uses `item_id=""`, `lease_id=null`, `agent_id="runtime"` and a fixed
runtime role. An empty item ID keeps a session observation out of CR item
grouping and completion calculations. A request rebuild may already have a
lease; rejection must preserve it rather than claim or release one.

## Persistence outcome policy

Canonical commit and projection materialization are separate boundaries. An
exception returned by a transaction call is not proof that COMMIT did not
happen: post-commit instrumentation may fail. Query only for this event's ID
when the commit result is uncertain; never retry the business action or append
another diagnostic as recovery.

| Observation | Diagnostic storage outcome | Projection outcome | Review outcome |
| --- | --- | --- | --- |
| Canonical commit confirmed; materialization succeeds | `committed` | `current` | Original rejection |
| Canonical commit confirmed; materialization fails | `committed` | `failed` | Original rejection |
| Transaction fails; canonical read confirms event absent | `not_committed` | `not_attempted` | Original rejection |
| Transaction result uncertain; canonical read confirms event present | `committed` | Materialize independently | Original rejection |
| Transaction and canonical confirmation fail | `unknown` | `not_attempted` | Original rejection |
| No current canonical session exists | `not_committed` | `not_attempted` | Original rejection; no session created |

The additive summary diagnostic includes its own schema version, bounded
storage/projection outcome, the event ID when committed, and an allowlisted
failure category when needed. It never includes an exception's text. Storage
failure remains visible in JSON output and OTel; it is not a silent fallback.

## Privacy, telemetry and compatibility

Construct the payload from an allowlist. Do not copy arbitrary dictionaries,
exceptions, raw messages, argv, prompts, paths, URLs, usernames, agent IDs,
refs or commit/tree OIDs. Accept only the two reason codes above and known
stack invariant values; omit unrecognized invariant text. The existing outer
evidence schema retains its local session identity; do not duplicate that
identity into the payload or telemetry.

Add `request_rejection` to the persistence operation allowlist so the existing
transaction instrumentation stays attached to real work. Add one checkpoint
event on the current span for the bounded reason and storage/projection
outcomes. Do not create a new span, synthetic process parent, external import
format, duration counter, or telemetry-backed completion rule. Telemetry
failure remains fail-open and cannot replace the original rejection.

This is an additive evidence/diagnostic contract. Existing stdout fields,
protocol versions, leases, final-gate policy, and normalized finding inputs
remain unchanged. No migration is required. Existing human audit summary text
does not become a new rejection reporting surface; the durable record lives
in canonical evidence and its existing projection/archive.

## Behavior intent and verification

Observable behavior: a rejected request's reason remains queryable in the
workspace's evidence projection and canonical store after the process exits,
without changing business state. The initial regression test must fail because
the existing rejection leaves no committed session-scoped event, not because
of setup, permissions, or an unavailable GitHub service.

Use temporary real SQLite stores and fake GitHub observations. Contract tests
must cover both reason codes, single and batch entrypoints, existing-lease
rebuild, repeated same-second calls, unchanged successful/unstacked-unavailable
requests, preservation of concurrent canonical updates, and unchanged item,
lease, gate and CR item-count outcomes. Cover a separate process reading the
record, idempotent evidence replay, projection loss/rebuild, and archive backup.

Failure tests must distinguish pre-commit failure, post-commit uncertainty,
canonical-confirmation failure, and projection-only failure. Assert bounded
payload and OTel fields with unsafe input and verify telemetry failure preserves
the original rejection. Pure stack-refresh tests may isolate this new storage
boundary; production must not contain a special path for their fake sessions.

Record RED before implementation, GREEN afterward, then run the surrounding
request/lease/persistence contracts and the repository's required lint, type,
full unit, CLI, manifest and payload checks. This work does not by itself claim
completion of either real PR's review session or a live `final-gate`.

## Complexity budget and reviewer acceptance

Reuse the existing event, transaction, projection and archive mechanisms. The
simpler alternative of saving the refresh session is rejected because it can
overwrite concurrent canonical state. Appending JSONL directly is rejected
because that would make a projection a second writer. Treating a projection
exception as a failed commit is rejected because it misreports durable state.

Acceptance requires one local helper and its two call sites, no general-purpose
diagnostic subsystem, and executable evidence for the outcome table above.
Read-only design review identified the post-commit ambiguity, same-second ID
collision, unsafe invariant copying and stale-session risks reflected here;
implementation review remains required after the tests and code exist.

## Review correction: bounded reader diagnostics

The persistence privacy allowlist also includes the existing stack-reader causes
for malformed objects, missing member pull requests, invalid pagination and
selected-entry mismatches. Regression coverage checks that all seven reader
causes survive persistence with the same diagnostic as the rejection output;
unsafe input remains excluded. This repairs the existing observation contract
without changing state ownership, gate policy, event shape or side effects.
The allowlist stays at the persistence privacy boundary. Sharing reader constants
is deferred to avoid expanding this corrective patch into a reader refactor;
this change introduces no new diagnostic names or runtime state.
