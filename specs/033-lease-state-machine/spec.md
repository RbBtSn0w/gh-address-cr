# Feature Specification: Lease State Machine Contract

**Feature Branch**: `033-lease-state-machine`  
**Created**: 2026-09-21  
**Status**: Draft  
**Input**: Issue #284 ("Write down the lease state machine contract"), the root cause
of the defects fixed under issue #273 (PRs #274–#279, #283).

## Why this exists

Constitution Article VI requires item-scoped claim leases and says they must have
"lease policies (expiry, reclaiming, conflict detection)". It does not say what a
lease is, which transitions exist, who may trigger them, or what a caller may assume
about a lease it did not create. Those rules lived in the heads of whoever last touched
`issue_action_request`, `claimed_fixer_lease`, `agent_batch` and `leases.py`, and in
tests that each pin one behaviour.

That gap produced a defect class rather than a single bug. Seven PRs (#274–#279, #283)
fixed variants of it, each found at a newly discovered entry point or edge. The table lists
the distinct rules they were missing:

| Symptom | Missing rule |
|---|---|
| A rejected `--publish` left a lease that locked the item (#273) | A failed one-shot command must not leave a lease it created |
| A rollback released a lease the agent had acquired earlier (#279) | Only the creator may roll a lease back |
| Re-entry handed back a request that did not belong to the lease (#279) | What is handed to an agent must be submittable |
| A rejected batch said nothing was accepted when rows were (#278) | What the runtime says must match the ledger |
| A rebuilt request left no `request_issued` event (#283) | What the runtime says must match the ledger |

Auditing every lease-creating entry point against these rules found two more that
violated the first one; both are fixed under this spec (see Assumptions). The rules are stated once here so the next
entry point is checked against them, not discovered by its first failure.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - An agent is never locked out by its own failed command (Priority: P1)

As an agent running a one-shot command that claims a lease internally, I need a failure
after the claim to leave the item claimable, because I hold no request file and no
skeleton to retry with.

**Why this priority**: This is the reported defect (#273) and its recurrences. A stranded
lease blocks the item until its TTL, and `agent reclaim` does not free a still-valid one.

**Independent Test**: For every entry point that creates a lease inside a single command,
inject a failure after the claim and assert no active lease for that item remains.

**Acceptance Scenarios**:

1. **Given** an item and a one-shot command that claims then reaches a modeled,
   recoverable post-claim failure, **When** the command returns its error, **Then** no
   lease created by that command is `active` or `submitted`, and the item is claimable
   again.
2. **Given** an agent that claimed through `agent next` and then runs a one-shot command
   on the same item which fails, **When** the command returns, **Then** the lease the
   agent already held is unchanged.

### User Story 2 - Two-step flows keep their lease across a rejected submit (Priority: P1)

As an agent using `agent next` then `agent submit` (or `agent next --batch`), I need my
lease to survive a rejected submit, because I still hold the skeleton and will correct
and resubmit against the same lease.

**Independent Test**: Reject a submit for each two-step flow and assert the lease is
still `active` with an intact request.

**Acceptance Scenarios**:

1. **Given** a lease from `agent next`, **When** `agent submit` is rejected, **Then** the
   lease is `active` and the same `lease_id` accepts the corrected response.

### User Story 3 - The owner can recover its own lease (Priority: P2)

As an agent that lost its request files, I need `agent next --item-id` to hand me the
request for the lease I already hold, because I can neither submit nor claim again
otherwise.

**Independent Test**: Delete the request and skeleton of an active lease, re-enter as the
owner, and assert the returned request submits.

**Acceptance Scenarios**:

1. **Given** an active fixer lease and lost files, **When** the owner re-enters in item
   mode, **Then** the request is rebuilt under the original `request_id` and `lease_id`,
   a `request_issued` event is recorded, and a response written earlier still submits.
2. **Given** a lease held by another agent, a non-fixer role, a `submitted` lease, or an
   expired lease, **When** an agent re-enters, **Then** none of them is re-entered.

### Edge Cases

- `submitted` is transient. `submit_lease` is always followed immediately by
  `accept_lease` on the same lease in one call, so no session on disk ever holds a
  `submitted` lease and "evidence sent but not yet accepted" is not a state the runtime has.
  The table's `submitted` row describes the operations in isolation; its `expire` cell is
  unreachable in production (FR-008).
- `expire_leases` on a terminal lease is a no-op, not an error.
- The orchestrator keeps its own in-memory shadow lease per item. A conflict granting the
  shadow lease must not strand the core lease that was already issued.
- A one-shot command that claims several items and fails part-way must release every
  lease it created, and only those.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001 (I1, no stranded leases on modeled failures)**: A command that creates a
  lease and then returns a modeled, recoverable post-claim failure MUST release every
  lease it created before returning, unless it is a two-step flow that hands the agent
  the request and skeleton to retry with. An unexpected exception is not automatically
  safe to roll back because the runtime may not know which effects completed; it retains
  the lease for inspection, owner recovery, or TTL expiry instead of guessing.
- **FR-002 (I2, creator-only rollback)**: A rollback MUST release only a lease its own
  call created. A lease the caller held before the call MUST be left unchanged.
- **FR-003 (I3, submittable hand-back)**: Whatever the runtime hands an agent for a lease
  it already holds (request path, skeleton path, identity) MUST be usable by
  `agent submit`: parseable, an `ActionRequest`, carrying this lease's `request_id` and
  `lease_id`, with the lease's stored `request_hash` equal to the hash of the request on
  disk.
- **FR-004 (I4, ledger honesty)**: The ledger MUST record `request_issued` exactly when
  an `ActionRequest` is written, and MUST NOT when none is. Status and recovery text MUST
  agree with what the ledger and session record; a payload must not say evidence was
  published or accepted when it was not, nor deny partial acceptance that occurred.
- **FR-005 (transition and claim tables)**: The lease statuses, the transitions between
  them, and what a new claim does when the item already has a lease in each status, are
  exactly those in `contracts/lease-transitions.md`, and an executable test asserts every
  cell of both tables. `claim` is not a transition out of a status: it creates a new
  `active` lease and is constrained by the status of the item's *other* leases, so it is
  a second table rather than a column of the first.
- **FR-006 (entry-point inventory)**: Every call site that creates a lease is listed in
  `contracts/lease-entry-points.md` with its class (one-shot, two-step, batch,
  orchestrated) and the rule that protects it. A test fails when a call site exists that
  is not listed.
- **FR-007**: This feature MUST NOT change lease TTLs, the set of statuses, or any public
  CLI, reason code or exit code.
- **FR-008 (submitted is transient)**: `submit_lease` MUST be followed, as the very next
  statement, by `accept_lease` on the same lease, so no lease is ever at rest in
  `submitted`. Splitting the two is a contract change that makes a submitted lease
  observable and expirable, and must be decided explicitly.
- **FR-009 (bounded correctness claim)**: This feature defines and verifies sequential
  lease transitions and composition-level rollback ownership. It MUST NOT be described
  as cross-process claim atomicity or crash consistency for `session.json` and the
  evidence ledger; those require a transactional persistence boundary not added here.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: Affects session lease state and the evidence ledger's
  request events. `session.json` stays the authoritative owner of leases; the
  orchestrator's in-memory lease is a shadow of it (Constitution, Runtime State) and must
  not outlive or contradict the core lease it shadows. No GitHub IO changes.
- **Runtime Kernel Model**: See `plan.md` (Architecture Preflight). External facts are
  the lease records and item states in `session.json`; the transition table is the policy
  table; there is no new side effect.
- **CLI / Agent Contract Impact**: None to commands, reason codes or exit codes. Guidance
  text that names recovery steps is corrected where it named a command that could not
  perform the recovery (done in #279). No Status-to-Action Map behaviour changes.
- **Evidence Requirements**: A lease that reaches `accepted` still requires the existing
  submit path; this feature adds no way to accept evidence.
- **Packaged Skill Boundary**: The contracts live under `specs/`. `skill/` keeps only the
  agent-facing consequences already in `agent-protocol.md` and `evidence-ledger.md`.
- **External Intake Replaceability**: Unaffected.
- **Telemetry Evidence Boundary**: Unaffected.
- **Architecture Plateau Risk**: This is the response to that risk. Review feedback on
  #279 added edge branches to one function five times without reducing the state space;
  AGENTS.md says to stop and write an architecture spec. This spec reduces the state
  space by naming four invariants and one table, and by making the set of entry points an
  asserted fact instead of an assumption.
- **Fail-Fast Behavior**: A lease-creating call site missing from the inventory fails the
  build. A transition outside the table is an error, not a silent fallback.

### Key Entities

- **Lease**: `lease_id`, `item_id`, `agent_id`, `role`, `status`, `request_id`,
  `request_hash`, `request_path`, `resume_token`, `expires_at`, `reason`.
- **Item claim marker**: `item.state = "claimed"` and `item.active_lease_id`, set when a
  lease is claimed and reset when it is released, expired or rolled back.
- **Shadow lease**: the orchestrator's in-memory `LeaseRecord`, keyed by `item_id`,
  holding a token and `context_key`. It has no terminal states; releasing deletes it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every lease-creating entry point satisfies FR-001 for each modeled failure
  it returns, or is a documented two-step flow, verified by one failure-injection test
  per protected failure boundary.
- **SC-002**: The 24-cell transition table (6 statuses x 4 operations) and the 6-cell
  claim table (one per status of the item's existing lease) are each asserted by a test
  that fails on any change to them.
- **SC-003**: Adding a lease-creating call site without listing it in the inventory fails
  the test suite.
- **SC-004**: No public command, reason code or exit code changes.

## Assumptions

- **Two entry points violated FR-001** and are fixed under this spec, each with a
  failing test first:
  1. `orchestrator/harness.py` `handle_step`: the core lease is issued, then the shadow
     `grant_lease` raises `LeaseConflictError` when two items share a `context_key`. The
     core lease stays `active` with no shadow, so the item is locked.
  2. `workflow_matching.py` `_process_fast_fix_matches` (`agent resolve --commit --files`):
     a failure of the batch submit leaves every claimed lease active, and the command is
     one-shot so the caller has no skeleton to retry with.
- **Withdrawn**: an earlier draft asked whether a `submitted` lease should be exempt from
  TTL expiry. The question does not arise: no lease is ever at rest in `submitted` (FR-008).
- **Open question, not decided here**: the orchestrator's shadow lease and the core lease
  disagree on what conflicts. The shadow refuses two items on the same file (its
  `context_key` is the path); `claim_lease` allows them when their hunks do not overlap.
  This spec only makes the disagreement safe (the core lease is released and the step
  answers `RETRY`); aligning the two policies is a separate decision.
- **Open question, not decided here**: batch submit is not atomic; rows are accepted one
  at a time into an append-only ledger, and a later failure leaves earlier rows accepted.
  The recovery text is truthful (#278). Making it atomic needs a decision about what
  happens to already-written ledger entries.
- **Required follow-up architecture work**: claims are currently implemented as
  load/mutate/atomic-replace of `session.json`. Atomic replacement prevents torn JSON but
  does not prevent two processes from reading the same revision and overwriting one
  another. A later architecture spec must define one transactional lease mutation
  boundary (including cross-process serialization or compare-and-swap), make acquisition
  provenance explicit (`created` versus `re-entered`), derive item claim markers from one
  canonical owner, reconcile the orchestrator shadow policy with core conflict policy,
  and define session/ledger crash recovery. Until that work lands, this spec proves the
  sequential state machine only.
