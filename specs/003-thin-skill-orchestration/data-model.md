# Data Model: Thin Skill Orchestration

## SkillAdapter

Represents the shipped skill entrypoint and references that route agents to the runtime.

**Ownership**

- `owner`: packaged skill documentation
- `persisted_by`: files under `gh-address-cr/`
- `mutated_by`: repository maintainers during skill releases
- `forbidden_mutators`: runtime sessions and AI agents during PR handling

**Fields**

- `entrypoint`: first-read instruction surface for installed agents
- `public_commands`: high-level runtime commands exposed as agent-safe
- `advanced_references`: optional skill-owned references for detailed integration
- `compatibility_requirements`: runtime availability and version requirements
- `status_action_map`: supported runtime status outcomes and safe next actions

**Validation Rules**

- Must not own session mutation, GitHub side effects, lease mutation, evidence acceptance, or final-gate decisions.
- Must use skill-root-relative paths inside packaged skill docs.
- Must route to `review` as the default public workflow entrypoint.

## RuntimeCLI

Represents the deterministic control plane used by humans, agents, CI, and future runners.

**Ownership**

- `owner`: runtime package
- `persisted_by`: repository source and installed runtime package
- `mutated_by`: runtime implementation changes
- `forbidden_mutators`: packaged skill prose and direct AI session edits

**Fields**

- `public_entrypoint`: default review command
- `machine_summary`: structured runtime output
- `agent_protocol`: supported action request and response contracts
- `lease_policy`: claim, expiry, conflict, reclaim, and submission rules
- `final_gate`: authoritative completion proof

**Validation Rules**

- Must remain the owner of session state, GitHub IO, evidence ledger writes, publishing, and final-gate evaluation.
- Must fail loudly for malformed inputs and unsupported producer formats.
- Must serialize GitHub reply and resolve side effects.

## MachineSummary

Represents one runtime command outcome consumed by the adapter and agents.

**Ownership**

- `owner`: runtime package
- `persisted_by`: runtime output and run artifacts
- `mutated_by`: runtime command execution
- `forbidden_mutators`: skill adapter and external agents

**Fields**

- `status`
- `reason_code`
- `waiting_on`
- `next_action`
- `repo`
- `pr_number`
- `item_id`
- `item_kind`
- `counts`
- `artifact_path`
- `exit_code`

**Validation Rules**

- `status`, `reason_code`, `waiting_on`, and `next_action` must be sufficient to choose a safe next action or stop condition.
- Missing or unknown required status fields must fail loudly.
- Human prose must not be the adapter's source of truth.

## StatusActionMap

Maps runtime machine summaries to safe adapter behavior.

**Ownership**

- `owner`: adapter contract derived from runtime machine summary
- `persisted_by`: packaged skill references and contract docs
- `mutated_by`: repository maintainers when runtime status semantics change
- `forbidden_mutators`: live PR sessions and agent-local memory

**Fields**

- `status`
- `reason_code`
- `waiting_on`
- `required_artifacts`
- `safe_next_action`
- `stop_condition`
- `forbidden_actions`

**Validation Rules**

- Every stable public review status maps to exactly one safe next action or one explicit stop condition.
- Unknown statuses must stop rather than fall back to guessing.
- Completion entries must require final-gate proof.

## AgentRole

Represents a named responsibility boundary for one worker in the PR session.

**Ownership**

- `owner`: runtime agent protocol contract
- `persisted_by`: runtime schemas and contract docs
- `mutated_by`: runtime contract changes
- `forbidden_mutators`: role-specific agents during active work

**Fields**

- `role_name`
- `allowed_actions`
- `required_inputs`
- `required_evidence`
- `forbidden_side_effects`
- `handoff_outputs`

**Validation Rules**

- Mutating roles require active claim leases.
- Publisher and gatekeeper authority remain runtime-owned deterministic roles.
- Agents must not post replies, resolve threads, or mutate shared session state directly.

## CapabilityManifest

Represents what an agent or adapter can safely perform.

**Ownership**

- `owner`: runtime agent protocol
- `persisted_by`: runtime validation inputs and fixtures
- `mutated_by`: agent/provider configuration before lease issuance
- `forbidden_mutators`: runtime after a lease is issued for that request

**Fields**

- `schema_version`
- `agent_id`
- `supported_roles`
- `supported_actions`
- `supported_request_formats`
- `supported_response_formats`
- `constraints`

**Validation Rules**

- Work assignment requires compatible role, action, request format, and response format.
- Incompatible or missing manifests block lease issuance.
- Manifests do not grant side-effect authority outside the runtime.

## ActionRequest

Represents a runtime-issued work request for one item under a lease.

**Ownership**

- `owner`: runtime
- `persisted_by`: runtime request artifacts
- `mutated_by`: runtime work assignment
- `forbidden_mutators`: assigned agents, skill adapter, and manual session edits

**Fields**

- `request_id`
- `lease_id`
- `agent_id`
- `role`
- `item_id`
- `item_kind`
- `allowed_resolutions`
- `required_evidence`
- `forbidden_actions`
- `resume_command`
- `request_hash`

**Validation Rules**

- Must match an active lease before any response can be accepted.
- Must include enough item context for the agent to act without reading session internals.
- Must forbid direct GitHub side effects from AI agents.

## ActionResponse

Represents an agent's structured output for one action request.

**Ownership**

- `owner`: assigned agent until submission; runtime after acceptance or rejection
- `persisted_by`: response artifact and evidence ledger
- `mutated_by`: assigned agent before submission, runtime when recording outcome
- `forbidden_mutators`: non-holder agents and skill adapter

**Fields**

- `request_id`
- `lease_id`
- `agent_id`
- `role`
- `item_id`
- `resolution`
- `note`
- `changed_files`
- `validation_commands`
- `reply_markdown`
- `evidence`

**Validation Rules**

- Must match the active lease and request context.
- `resolution` must be `fix`, `clarify`, `defer`, or `reject`.
- Fix responses require changed-file and validation evidence.
- Clarify, defer, and reject responses require reply or rationale evidence.
- Stale, duplicate, cross-role, or malformed responses are rejected and recorded.

## ClaimLease

Represents bounded ownership of one item or conflict area.

**Ownership**

- `owner`: runtime lease manager
- `persisted_by`: session state and evidence ledger
- `mutated_by`: runtime lease issuance, submission, expiry, release, and reclaim operations
- `forbidden_mutators`: agents and skill prose

**Fields**

- `lease_id`
- `item_id`
- `agent_id`
- `role`
- `state`
- `created_at`
- `expires_at`
- `conflict_keys`
- `request_hash`

**Validation Rules**

- Only active lease holders can mutate item state.
- Overlapping item, thread, file, or side-effect conflict keys force serialization.
- Expired leases may be reclaimed without deleting accepted evidence.

## EvidenceLedger

Represents the audit trail for orchestration.

**Ownership**

- `owner`: runtime
- `persisted_by`: PR session audit artifacts
- `mutated_by`: runtime state transitions and publishing operations
- `forbidden_mutators`: direct manual edits and skill adapter logic

**Fields**

- `event_id`
- `timestamp`
- `actor`
- `role`
- `item_id`
- `lease_id`
- `request_id`
- `event_type`
- `payload`

**Validation Rules**

- Accepted and rejected submissions must be recorded.
- Publishing side effects must be recorded with reply and resolve evidence.
- Final-gate outcomes must be recorded before completion claims.

## ReviewProducerIntake

Represents input from a replaceable review producer.

**Ownership**

- `owner`: runtime intake contract
- `persisted_by`: producer handoff files and normalized finding artifacts
- `mutated_by`: producer before ingestion, runtime during validation and normalization
- `forbidden_mutators`: downstream fixer/verifier agents

**Fields**

- `producer_id`
- `format`
- `findings`
- `source_artifact`
- `validation_result`

**Validation Rules**

- Accepted input must be normalized findings or fixed `finding` blocks.
- Narrative-only output is rejected with actionable guidance.
- Producer identity must not change downstream completion semantics.

## OrchestrationRunbook

Represents the human-usable multi-agent coordination flow.

**Ownership**

- `owner`: product documentation
- `persisted_by`: packaged references and repository docs
- `mutated_by`: repository maintainers
- `forbidden_mutators`: runtime session execution

**Fields**

- `preflight_checks`
- `role_sequence`
- `parallelization_rules`
- `handoff_steps`
- `validation_steps`
- `final_gate_step`

**Validation Rules**

- Must be executable without a custom autonomous runner.
- Must not introduce non-PR workflows.
- Must preserve runtime-mediated state changes and final-gate authority.
