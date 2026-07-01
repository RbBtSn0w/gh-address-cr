# Phase 1 Data Model: Evidence-Gated Runtime Consolidation

Derived from the spec's Key Entities and the Architecture Preflight. All entities
are deterministic dataclasses under `src/gh_address_cr/core/consolidation/`.
Runtime facts remain authoritative; entities below are either control artifacts
(`rollout-state.v1`) or side-effect-free projections.

## RuntimeAuthorityMap

One owner and derived-output boundary per state axis (FR-001, SC-001).

| Field | Type | Rules |
|-------|------|-------|
| `axis` | enum {`review_item`, `lease`, `check`, `side_effect_evidence`, `telemetry_evidence`, `final_gate_eligibility`, `local_finding`} | required; unique per map |
| `authoritative_owner` | enum {`legacy`, `kernel`} | required |
| `compatibility_direction` | enum {`legacy_from_kernel`, `kernel_from_legacy`, `none`} | required; `none` only when a single path exists |
| `slice_id` | string \| null | the Migration Slice responsible for this axis |

**Validation**: exactly one entry per `axis`; two entries claiming the same axis
with different owners → fail loud (`DUPLICATE_STATE_OWNER`). During partial
migration the map must enumerate every axis (FR-019).

## MigrationSlice

A reversible unit of authority transfer (FR-002, FR-003).

| Field | Type | Rules |
|-------|------|-------|
| `slice_id` | string | required; stable identifier |
| `axes` | list[axis] | non-empty; axes this slice moves |
| `external_facts` | list[str] | fact/event kinds the slice consumes |
| `authoritative_projection` | str | kernel projection that becomes owner |
| `deterministic_policy` | str | policy/decision function reference |
| `side_effect_boundary` | str | command/outbox plan reference; must be idempotent |
| `compatibility_projection` | str \| null | derived output preserving legacy consumers |
| `replay_coverage` | list[str] | contract-test references proving parity/recovery |
| `supported_cohort` | str | PR/host cohort the slice applies to |
| `rollback_trigger` | RollbackTrigger | required |

**Validation**: a slice missing any of facts/projection/policy/side-effect
boundary/replay coverage/cohort/rollback cannot advance past `shadow`
(FR-003/FR-004). A candidate that writes a side effect during projection or
policy evaluation fails the slice contract (Edge Case).

## CompatibilityProjection

A derived representation that preserves supported consumers without owning truth.

| Field | Type | Rules |
|-------|------|-------|
| `source_owner` | enum {`legacy`, `kernel`} | the authoritative side |
| `target_consumer` | str | the surface kept stable (e.g. `threads` output) |
| `versioned` | bool | true if the projection changes a public contract |

**Validation**: never authoritative; deleting it must not lose runtime truth.

## ParityObservation

A side-effect-free comparison of current and candidate behavior (FR-007, SC-003).

| Field | Type | Rules |
|-------|------|-------|
| `slice_id` | string | required |
| `fact_digest` | string | digest of the replayed fact set (determinism anchor) |
| `projection_match` | bool | legacy vs candidate projection equality |
| `decision_match` | bool | policy-decision equality |
| `command_plan_match` | bool | planned-command (idempotency key + payload digest) equality |
| `differences` | list[Difference] | empty when all match |
| `side_effects_executed` | int | MUST be 0 |

**Validation**: `side_effects_executed != 0` → fail loud. Any unexplained
difference blocks default rollout (FR-008, SC-004).

## OptimizationHypothesis

One proposed cost/complexity improvement with independent guardrails (FR-010,
FR-015, SC-007).

| Field | Type | Rules |
|-------|------|-------|
| `hypothesis_id` | enum {`output_truncation`, `command_session`, `workflow_surface_removal`} | required; unique |
| `expected_benefit` | str | target cost dimension (tokens/latency/complexity) |
| `protected_guardrails` | list[str] | provisional + durable quality outcomes that must not regress |
| `cohort_rules` | str | supported cohort |
| `staged_enablement` | RolloutStage | current stage |
| `stop_condition` | str | measurable regression that halts rollout |
| `rollback_action` | str | how the default reverts |
| `safe_fallback` | str | non-session / `--full` path kept available (FR-011/FR-012) |

**Validation**: accepted/rejected/rolled back independently of the other two
(SC-007). Lossy truncation cannot be default until guardrails hold and the output
contract is preserved or versioned (FR-012).

## RolloutGate / RolloutState (`rollout-state.v1` artifact)

Deterministic conditions controlling stages (FR-008, SC-004/SC-008).

| Field | Type | Rules |
|-------|------|-------|
| `schema` | const `rollout-state.v1` | required |
| `slice_id` | string | required |
| `stage` | enum {`shadow`, `opt_in`, `default`, `deprecating`, `deleted`} | monotonic except on rollback |
| `enabled` | bool | operator/CI-controlled |
| `evidence_ref` | str \| null | feature-023 comparison result reference |
| `deprecation_window_complete` | bool | required `true` before `deleted` |

**State transitions** (RolloutPolicy):

```text
shadow --(parity ok + provisional evidence)--> opt_in
opt_in --(acceptance gate + durable feature-023 evidence)--> default
default --(gate holds + deprecation initiated)--> deprecating
deprecating --(deprecation_window_complete + tests/docs/skill updated)--> deleted
any stage --(rollback trigger breached)--> previous supported stage
```

**Validation**: forward transition blocked on `INSUFFICIENT_EVIDENCE`, unexplained
parity diff, or quality regression (FR-014). `deleted` requires
`deprecation_window_complete == true` and provisional-only evidence is rejected
for `default`/`deleted` (SC-008). Rollback restores the prior stage without
rewriting runtime facts (FR-016, SC-005).

## RollbackTrigger

A measured condition requiring a stage reversal.

| Field | Type | Rules |
|-------|------|-------|
| `dimension` | enum {`parity`, `quality`, `economics`, `operational_health`} | required |
| `threshold` | str | measurable stop condition |
| `reversal_stage` | RolloutStage | stage to return to |

**Validation**: breach forces reversal via a `rollout-state` transition only; it
never discards valid runtime facts or reconstructs truth from reports (Edge Case).
