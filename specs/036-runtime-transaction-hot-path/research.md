# Research: Remaining Whole-Session Cost

**Date**: 2026-09-28
**Decision state**: Corrected architecture accepted and implemented

## Question

Why does the degradation ratio remain above `2.0` after transactions normalize
and encode only changed entities and reuse the already-loaded committed
snapshot?

## Evidence

The reverted prototype established these contracts:

- a normal transaction calls `_load_snapshot` once;
- save/materialization reuses the committed snapshot;
- action-request preflight hands its loaded payload into the transaction;
- only dirty items and leases are normalized and encoded;
- `session.json` assembled from stored fragments is byte-identical to a full
  compact `json.dumps` rebuild over randomized mutations.

Profile M nevertheless moved only from degradation `2.801` to `2.386`. This
rules out repeated normalization and re-encoding as the complete cause.

Two total-size costs remain:

1. `_load_snapshot` executes `json.loads` for every item and lease row before
   the command's target is known to the in-memory mutation callback.
2. Compatibility materialization atomically replaces `session.json`, so every
   committed revision still writes the complete projection even when most JSON
   fragments are reused.

A temporary profile-M run that patched the projection writer to a no-op still
reported degradation `2.295` (p50 `33.230 ms`, p90 `44.778 ms`). The complete
projection write is measurable, but it is not the dominant source of growth.
This moves candidate B below lazy canonical decoding in the decision order.

## Rejected Direction

Do not add operation-specific loaders or command-specific dirty flags for
classification, action request, and submit. That would duplicate selection,
lease, and conflict policy outside the existing runtime kernel and expand the
state space each time a new command is added.

The first fragment encoder also used a Python character-by-character ASCII
conversion. It increased profile-M p50 to about `90 ms`; it was replaced by the
C-backed `ascii/backslashreplace` conversion and exact Unicode equivalence
tests. This confirms that fragment reuse only helps when the fragment boundary
itself stays cheap.

## Candidate Designs

### A. Canonical lazy entity view — preferred research direction

Retain row IDs, indexed columns, and canonical `payload_json` fragments at load
time. Decode an item or lease only when existing dict-compatible code accesses
its value. Iteration remains correct but pays the full decode cost only for
commands that actually iterate the collection.

This preserves one generic transaction API and keeps SQLite authoritative. It
must prove normal dict behavior, mutation tracking, equality, error timing,
claim projection correctness, and byte-identical compatibility output.

The item half of this design was validated in the reverted prototype, but it is not sufficient by itself.
After removing an eager helper enumeration and combining lazy items with the
tracked submit path, profile M reached p50 `26.304 ms` while degradation stayed
at `2.436`. The remaining row growth is terminal leases, not items.

### B. Deferred compatibility materialization

Write projections only at explicit compatibility/recovery boundaries rather
than after every transaction. This could remove the remaining full-file write,
but it changes artifact freshness and crash-recovery expectations. It is not a
performance-only fallback and cannot proceed without a revised public contract,
Architecture Preflight, and migration/recovery tests.

### C. Operation-specific SQL transactions — rejected by default

Implement targeted SQL for every command. It may be fastest, but duplicates
runtime policy and creates multiple behavioral authorities. Reconsider only if
the generic lazy view is experimentally unable to meet the budget.

## Next Proof Sequence

1. Add a RED contract that a targeted item mutation does not decode unrelated
   item payloads.
2. Prototype the smallest generic lazy entity map behind `RuntimeStore`.
3. Rerun profile M before widening the change.
4. If M remains above `1.5`, benchmark projection output without entity decode
   to establish whether the public materialization contract is the floor.
5. Revise the preflight before any schema-version or artifact-cadence change.

No option is accepted merely because it improves absolute latency. SC-001 and
the existing correctness/recovery contracts remain the decision boundary.

## Revised next direction: indexed lazy leases

SQLite already stores low-cardinality lease policy fields (`status`, `item_id`,
`agent_id`, `role`, request identifiers, and timestamps) separately from
`payload_json`. A generic lease view can therefore expose these indexed values
for expiry/conflict scans and decode the canonical payload only when a caller
needs full history, conflict keys, or mutation.

This does not authorize deleting terminal leases or hiding them from list and
recovery surfaces. The proof sequence is:

1. terminal lease payloads remain present in `session.json` and `agent leases`;
2. active-policy scans do not `json.loads` terminal payloads;
3. mutating a selected lease marks and writes exactly that lease;
4. projection equivalence and committed-view equality remain exact;
5. profile M must materially reduce the last/first-decile slope before the
   abstraction is widened or accepted.

### Result: rejected

The prototype implemented lazy item and lease dict subclasses, tracked nested
container wrappers, fragment-aware projection, an active lease index, and
tracked submit. Absolute profile-M p50 fell as low as `23.748 ms`, but the best
degradation ratio remained `2.136`. The approach also added more than 1,000
lines to `runtime_store.py` and required private marker coupling in session and
item helpers.

That tradeoff violates the Spec 036 complexity budget. The production and test
prototype was reverted. The next architecture must expose a bounded,
versioned command working set directly from SQLite and keep full-session
materialization at explicit compatibility/reporting boundaries. It must not
emulate the entire mutable dict graph with proxy containers.

## Bounded Working-Set Result and Decision Gate

The replacement prototype confirms that explicit row selection is a viable
correctness boundary, but it does not yet satisfy the performance contract.
Across S/M/L the measured degradation ratios are `1.376`, `2.057`, and `3.452`.
All three command stages grow at L, so the failure is systematic rather than a
single outlier or one command-specific branch.

A temporary M run without post-commit compatibility materialization reduced
the classification slope to `1.805`, still above the `1.5` budget. Claim and
submit remained above `2.4` because their preflight still uses a full session
load. This establishes two independent remaining boundaries:

1. claim/submit must select their preflight working set without a full graph;
2. compatibility artifact freshness must have one non-contradictory contract.

The current plan says both that compatibility materialization remains after
commit and that the command hot path must not invoke full materialization
implicitly. Those statements cannot govern the same command path. The next
architecture decision must select and version one of these contracts:

- **Immediate projection:** every successful mutating command returns only
  after a current full compatibility projection exists. SC-001 must then be
  interpreted as including an unavoidable total-output-size cost, or the
  projection representation/benchmark budget must change.
- **Explicit projection boundary:** the SQLite commit marks projections dirty;
  command completion, compatibility reads, reporting, and recovery explicitly
  materialize the requested revision. SC-001 continues to measure the bounded
  mutation path, while separate artifact tests measure full projection cost.

The second option matches the stated SQLite authority and bounded-hot-path
design. Per-stage attribution later proved it was required only for the full
`session.json` projection: schema v3 first removed transaction growth by
normalizing lease events, then ADR-001 versioned explicit session projection
boundaries while keeping incremental evidence current.
