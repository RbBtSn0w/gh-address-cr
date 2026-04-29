# Data Model: Agent Control Plane

## ReviewSession

Represents one PR-scoped workflow.

Fields:

- `session_id`: stable identifier for the local session
- `repo`: `owner/name`
- `pr_number`: pull request number as string
- `status`: `IDLE`, `RUNNING`, `WAITING_FOR_EXTERNAL_REVIEW`,
  `WAITING_FOR_FIX`, `BLOCKED`, `NEEDS_HUMAN`, `PASSED`, or `FAILED`
- `items`: map of `item_id` to `WorkItem`
- `leases`: map of active `lease_id` to `ClaimLease`
- `ledger_path`: append-only evidence ledger path
- `resume_token`: opaque token for safe resume
- `metrics`: blocking item counts, unresolved thread counts, pending review
  counts, missing reply evidence counts

Relationships:

- Owns many `WorkItem` records
- Owns many `ClaimLease` records
- Appends many `EvidenceRecord` records

## WorkItem

Represents one actionable review unit.

Fields:

- `item_id`: stable item identifier
- `item_kind`: `github_thread` or `local_finding`
- `source`: `github`, `json`, `code-review`, `adapter`, or another producer id
- `title`: short issue title
- `body`: review body or normalized finding body
- `path`: optional file path
- `line`: optional line number
- `state`: `open`, `claimed`, `fixed`, `clarified`, `deferred`, `rejected`,
  `needs_human`, or `closed`
- `allowed_actions`: allowed actions for this item
- `classification_evidence`: optional recorded triage decision and rationale
  proving the item was classified before mutating work
- `conflict_keys`: optional file paths, remote thread ids, or side-effect
  targets used to prevent unsafe parallel claims
- `reply_evidence`: optional durable reply URL and author login
- `validation_evidence`: optional validation command records

Relationships:

- May have one active `ClaimLease`
- Has many `EvidenceRecord` entries
- For GitHub threads, may map to a remote thread id

## AgentRole

Defines a responsibility boundary for one agent or deterministic component.

Values:

- `coordinator`: deterministic CLI role that selects items and issues leases
- `review_producer`: AI agent or adapter that emits normalized findings
- `triage`: AI agent that classifies an item
- `fixer`: AI agent that modifies files and returns evidence
- `verifier`: AI agent or deterministic check that validates evidence
- `publisher`: deterministic CLI role that posts replies and resolves threads
- `gatekeeper`: deterministic CLI role that runs final-gate

Validation rules:

- `publisher` and `gatekeeper` are deterministic control-plane roles
- AI agents must not perform GitHub side effects directly
- Each role must declare supported actions in a `CapabilityManifest`

## CapabilityManifest

Declares what an agent or adapter can do.

Fields:

- `schema_version`
- `agent_id`
- `roles`: list of supported `AgentRole` values
- `actions`: list of supported actions such as `review`, `triage`, `fix`,
  `clarify`, `defer`, `reject`, `verify`
- `input_formats`: accepted request formats
- `output_formats`: emitted response formats
- `constraints`: optional limits such as max parallel claims
- `protocol_versions`: supported agent protocol versions

Validation rules:

- A role may be assigned only if the manifest declares that role
- An action may be requested only if the manifest declares that action
- A request format may be emitted only if the manifest declares support for it
- `constraints.max_parallel_claims` limits active leases for the agent

## ClaimLease

Represents item-scoped ownership for parallel work.

Fields:

- `lease_id`
- `item_id`
- `agent_id`
- `role`
- `status`: `active`, `submitted`, `accepted`, `rejected`, `expired`, or
  `released`
- `created_at`
- `expires_at`
- `resume_token`
- `request_hash`: hash of the `ActionRequest` issued for this lease
- `conflict_keys`: conflict keys reserved while the lease is active

Validation rules:

- Only one active lease may exist for one `item_id`
- Active leases must not reserve overlapping conflict keys unless the role is
  read-only
- A submitted `ActionResponse` must reference the active `lease_id`
- Expired leases may be reclaimed without deleting accepted evidence
- Rejected, expired, and released leases must append an evidence record

## ActionRequest

Structured payload sent from the control plane to an agent.

Fields:

- `schema_version`
- `request_id`
- `session_id`
- `lease_id`
- `agent_role`
- `item`: normalized `WorkItem` snapshot
- `allowed_actions`
- `required_evidence`
- `repository_context`
- `resume_command`
- `forbidden_actions`

Validation rules:

- Must include exactly one target item
- Must include a lease id for mutating work
- Must list required evidence for each allowed terminal action

## ActionResponse

Structured payload returned by an agent.

Fields:

- `schema_version`
- `request_id`
- `lease_id`
- `agent_id`
- `resolution`: `fix`, `clarify`, `defer`, or `reject`
- `note`
- `files`: changed files for `fix`
- `validation_commands`: commands run or expected validation commands
- `reply_markdown`: required for `clarify`, `defer`, or `reject`
- `fix_reply`: required for GitHub-thread `fix`
- `confidence`: optional numeric confidence

Validation rules:

- Must match an active lease
- Must include evidence matching the resolution type
- Must not claim GitHub side effects were performed by the agent
- Must fail if required evidence is missing

## EvidenceRecord

Append-only proof of accepted workflow state.

Fields:

- `record_id`
- `timestamp`
- `session_id`
- `item_id`
- `lease_id`
- `agent_id`
- `role`
- `event_type`: `request_issued`, `response_submitted`,
  `request_rejected`, `response_accepted`, `response_rejected`,
  `lease_created`, `lease_submitted`, `lease_accepted`, `lease_rejected`,
  `lease_expired`, `lease_released`, `reply_posted`,
  `classification_recorded`, `verification_rejected`, `thread_resolved`,
  `validation_recorded`, `gate_passed`, or `gate_failed`
- `payload`
- `payload_hash`

Validation rules:

- Records are append-only
- Side-effect records must include durable external identifiers where available
- Mutating fixer requests require prior `classification_recorded` evidence
- Missing classification may append `request_rejected` or `response_rejected`
  evidence, but must not create an active fixer lease, mutate files, mark an
  item terminal, or perform GitHub side effects
- Final completion requires a fresh `gate_passed` record
- Rejected responses, expired leases, exhausted retry budgets, and runtime
  compatibility failures must be recorded

## SideEffectAttempt

Represents one deterministic attempt to perform an external side effect.

Fields:

- `attempt_id`
- `session_id`
- `item_id`
- `side_effect_type`: `github_reply`, `github_resolve`, `github_review_state`,
  or `telemetry_export`
- `idempotency_key`
- `status`: `pending`, `succeeded`, `retrying`, `blocked`, or `failed`
- `retry_count`
- `backoff_until`: optional timestamp for scheduled retry after rate limits
- `last_error`
- `external_url`: durable URL or identifier when the side effect succeeds

Validation rules:

- Side effects must be serialized per work item
- Retry exhaustion must block the item without duplicating successful effects
- Rate-limit retries must record whether the next step is immediate retry,
  scheduled backoff, or blocking after exhaustion
- Successful GitHub replies must record durable reply evidence

## RuntimeCLI

Represents the independently installed deterministic control-plane product.

Fields:

- `runtime_version`
- `supported_protocol_versions`
- `supported_skill_contract_versions`
- `entrypoints`: console script and module invocation names
- `state_dir`: resolved session state root
- `capabilities`: supported command and protocol capabilities

Validation rules:

- Must own session mutation, GitHub side effects, and final-gate evaluation
- Must expose `review` as the primary public entrypoint
- Must fail fast when required tools such as `gh` are missing

## SkillAdapter

Represents the packaged skill layer used by AI agents.

Fields:

- `skill_version`
- `required_runtime_version`
- `required_protocol_version`
- `requirements_path`: skill-owned compatibility declaration path
- `instructions_path`
- `agent_hint_paths`
- `reference_paths`

Validation rules:

- Must not contain authoritative control-plane state transitions
- Must route agents to the runtime CLI for orchestration
- Must explain status handling and final-gate discipline
- Must block or fail loudly when the runtime is missing or incompatible

## CompatibilityShim

Represents legacy skill-local entrypoints retained during migration.

Fields:

- `shim_path`
- `delegated_entrypoint`
- `required_runtime_version`
- `failure_message`

Validation rules:

- Must delegate to `RuntimeCLI` for real work
- Must fail before session mutation when delegation is impossible
- Must not fork the runtime behavior into a second implementation

## RuntimeCompatibility

Represents the preflight compatibility decision between a skill/shim and the
installed runtime.

Fields:

- `skill_version`
- `required_runtime_version`
- `required_protocol_version`
- `runtime_version`
- `supported_protocol_versions`
- `status`: `compatible`, `missing_runtime`, `runtime_too_old`,
  `runtime_too_new`, or `protocol_unsupported`
- `remediation`

Validation rules:

- Incompatible or missing runtime status must fail before session mutation
- Compatibility checks must be recorded before adapter delegation

## LeasePolicy

Defines how parallel work ownership is assigned.

Fields:

- `lease_ttl_seconds`
- `max_parallel_claims_per_agent`
- `conflict_key_strategy`
- `reclaim_allowed_after`

Validation rules:

- Parallel fixer leases require distinct item IDs
- Known file-path or remote-thread side-effect conflicts prevent parallel fixer
  leases
- Read-only verifier or triage leases may share conflict keys only when they do
  not mutate state

## State Transitions

```text
open
  -> claimed
  -> fixed | clarified | deferred | rejected | needs_human
  -> closed

claimed
  -> open      # lease expires, is rejected, or is reclaimed
  -> closed    # accepted evidence plus required side effects complete

ReviewSession
  IDLE
  -> WAITING_FOR_EXTERNAL_REVIEW
  -> RUNNING
  -> WAITING_FOR_FIX
  -> RUNNING
  -> PASSED | BLOCKED | NEEDS_HUMAN | FAILED
```
