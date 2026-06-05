# Data Model: Runtime Kernel

## RuntimeFact

Represents one typed input to the runtime kernel.

**Fields**:

- `schema_version`: Version of the fact contract.
- `fact_kind`: One of `review_thread_observed`, `command_executed`, or `reporting_observed`.
- `fact_id`: Stable logical identity for this fact.
- `observed_at`: Observation timestamp used for deterministic ordering.
- `sequence`: Optional integer tiebreaker when multiple facts share an observation timestamp.
- `payload`: Fact-kind-specific data.

**Validation rules**:

- Unsupported `schema_version` fails loudly.
- Missing `fact_kind`, `fact_id`, or required payload identity fails loudly.
- Facts sort by `observed_at`, `sequence`, then `fact_id`.

## ReviewThreadFact

Represents an observed GitHub review-thread state.

**Fields**:

- `thread_id`: GitHub review-thread identity.
- `item_id`: Runtime work item identity, derived as `github-thread:<thread_id>` when not provided.
- `is_resolved`: Whether GitHub reports the thread as resolved.
- `is_outdated`: Whether GitHub reports the thread as outdated.
- `state`: Optional runtime-normalized state.
- `status`: Optional GitHub/session status.
- `path`, `line`, `url`, `body`: Source context.
- `reply_evidence_present`: Whether durable reply evidence is already recorded.
- `external_wait`: Whether the item requires external reviewer or producer input.

**State transitions**:

- unresolved or stale observations project to active work.
- resolved observations project to terminal work unless a later reopened observation exists.
- a later unresolved observation after terminal history marks the item as reopened.
- missing required reply/resolve execution evidence marks the item evidence-pending.

## CommandExecutionFact

Represents the recorded result of a planned side-effect command.

**Fields**:

- `command_id`: Idempotency identity of the planned command.
- `command_kind`: Side-effect kind such as `reply_thread`, `resolve_thread`, or `run_final_gate`.
- `item_id`: Related work item identity when item-scoped.
- `status`: `succeeded` or `failed`.
- `result_url`: Optional durable evidence URL.
- `recorded_at`: Result-recording timestamp.
- `source_fact_id`: Review-thread observation generation the planned command was created for.
- `source_observed_at`: Observation time for that review-thread generation.

**Validation rules**:

- Execution facts with unknown `command_id` references remain diagnostic until a matching plan can be correlated.
- Failed execution facts never satisfy completion evidence.
- Successful execution facts satisfy completion only when the command identity and source generation match the current projected review-thread generation and command kinds requiring external proof include durable, non-empty evidence such as a non-blank `result_url`.

## ReviewWorkItem

Represents one projected unit of review-resolution work.

**Fields**:

- `item_id`
- `thread_id`
- `source_fact_id`
- `source_observed_at`
- `state`: `active`, `terminal`, `stale`, `reopened`, `waiting`, or `evidence_pending`.
- `source_status`
- `is_resolved`
- `is_outdated`
- `reply_evidence_present`
- `required_commands`
- `completion_evidence`
- `failed_commands`
- `history`

**Relationships**:

- Derived from one or more `ReviewThreadFact` entries.
- May be satisfied by one or more successful `CommandExecutionFact` entries.

## ReviewProjection

Represents current PR review state derived from facts.

**Fields**:

- `work_items`
- `active_item_ids`
- `terminal_item_ids`
- `stale_item_ids`
- `reopened_item_ids`
- `waiting_item_ids`
- `evidence_pending_item_ids`
- `final_gate_blocker_ids`
- `diagnostics`

**Validation rules**:

- Projection output order is sorted by stable item identity.
- The same fact set always produces the same projection.

## PolicyDecision

Represents one deterministic next-state decision.

**Fields**:

- `status`: `blocked`, `ready_for_action`, `waiting_for_external_input`, or `final_gate_eligible`.
- `reason_codes`
- `item_ids`
- `next_action`

**Decision rules**:

- Diagnostics that indicate malformed or contradictory facts produce `blocked`.
- Active local-action or evidence-pending work produces `ready_for_action`.
- Waiting-only work produces `waiting_for_external_input`.
- No active, waiting, or evidence-pending work produces `final_gate_eligible`.

## PlannedCommand

Represents one side-effect command to execute outside projection and policy.

**Fields**:

- `command_id`
- `command_kind`
- `item_id`
- `idempotency_key`
- `reason_code`
- `payload`

**Validation rules**:

- Command IDs are derived from command kind, item identity, source generation, and required command payload.
- Regenerating a plan for the same state produces the same commands.
- Planned commands are not completion evidence.
