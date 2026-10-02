# Data Model: Transactional Lease Runtime

## Canonical Store

One `runtime.sqlite3` belongs to one PR workspace. The schema is versioned and
opened through one repository API. Table names below describe ownership and
constraints; exact SQL belongs to Phase A's executable schema contract.

## Entities

### `store_metadata`

- `schema_version` — monotonically versioned persistence contract.
- `store_id` — random local identity used for integrity diagnostics, never OTel.
- `created_at`, `updated_at`.
- `legacy_import_completed_at` and import source format version.
- `latest_revision` — last committed session revision.

Invariant: exactly one row. Unsupported future versions fail loudly.

### `sessions`

- `session_id` primary key.
- normalized repository and PR key (local state only; never telemetry).
- workflow status and metadata JSON for fields that are not policy indexes.
- `revision` integer with uniqueness per session.
- creation/update timestamps.

Invariant: one session per database; every successful runtime transition moves
revision N to N+1 exactly once.

### `items`

- `(session_id, item_id)` primary key.
- item kind, workflow state, classification, and normalized payload.
- current revision first/last observed.

Invariant: claimability is derived by joining canonical active leases. A mutable
`active_lease_id` compatibility field may appear in projections but is not an
independent database owner.

### `leases`

- `lease_id` primary key and `(session_id, item_id)` relationship.
- agent/role, status, created/expires/submitted/completed timestamps.
- request ID/hash/path binding and resume token.
- acquisition provenance: `created` or `reentered` for the returned transition.
- transition revision.

Invariant: the Spec 033 transition table remains valid. Database constraints and
transaction policy prevent conflicting active leases; terminal rows are retained
for audit.

### `lease_conflict_keys`

- `(lease_id, conflict_key)` primary key.
- normalized key type/value or an equivalent collision-safe normalized encoding.

Invariant: conflict lookup is part of the claim transaction. Raw paths remain
local and never enter telemetry.

### `evidence_events`

- monotonic local sequence for projection order.
- globally stable `record_id` unique key.
- session/item/lease references where applicable.
- actor role, event type, timestamp, payload JSON, payload hash.
- `transaction_id` and committed session revision.

Invariant: an event that describes a state transition commits in the same
transaction. Reinsert of the same record ID and content is idempotent; same ID
with different content is corruption.

### `outbox_commands`

- `command_id` primary key.
- unique `(session_id, effect_type, idempotency_key)`.
- planned-at revision and sanitized operation category.
- status: `planned`, `in_flight`, `succeeded`, `failed`, `unknown`.
- attempt count, retry boundary, last bounded error type, external result
  reference when safe for local evidence.

Invariant: `planned`/`in_flight`/`unknown` never satisfy success policy. A result
transition is a new canonical transaction and evidence event.

### `artifact_materializations`

- artifact kind (`session_json`, `evidence_jsonl`, or approved report).
- source revision, format version, status (`dirty`, `materializing`, `current`,
  `failed`), content hash, last attempt time, bounded error type.

Invariant: artifact status cannot alter runtime transition or final-gate truth.
Materialization is replace-by-revision and replayable.

### `migration_history`

- migration ID and from/to schema versions.
- started/committed timestamp and bounded outcome.
- legacy session hash and ledger hash for local audit only.

Invariant: migration commits once with imported state and events. Hashes and
paths never leave the local store or enter telemetry.

## Derived Projections

### Session dictionary v1 compatibility projection

Preserves existing public fields and datetime encoding. It adds or accompanies
versioned metadata containing source schema and revision. `items[*].state` and
`active_lease_id` are derived from the canonical lease relation.

### Evidence JSONL v1 compatibility projection

Orders canonical events by local sequence and emits the existing record shape.
Materialization uses atomic replacement, not append, so replay produces the same
complete file for a committed revision.

### Claim policy projection

For one transaction snapshot: current item, live leases after deterministic
expiry, overlapping conflict keys, holder/request binding, and expected revision.
The Spec 033 table reduces this projection to create, re-enter, or conflict.

### Worker dispatch projection

Contains canonical `lease_id`, revision, request binding, worker-delivery token,
and delivery status. It has no conflict keys, ownership TTL, lease status, or
release authority of its own.

## State Transitions

### Runtime transaction

`requested -> waiting_for_writer -> evaluating -> committed | rejected | busy | failed`

Only `committed` increments revision. `rejected`, `busy`, and `failed` persist no
partial state/event/outbox members, though bounded OTel may observe the attempt.

### Outbox command

`planned -> in_flight -> succeeded | failed | unknown`

`unknown` requires external reconciliation. Retry is allowed only by the effect's
documented idempotency policy and increments attempt count.

### Artifact materialization

`dirty -> materializing -> current | failed`

Opening a store with `failed`, missing, or older-revision artifacts schedules
repair. Canonical reads remain available.
