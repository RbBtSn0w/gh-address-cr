# Data Model: Orchestrator Integration

## Entities

### OrchestrationSession (Extended)
The persistent coordination state for the current PR.
- **run_id**: Unique ID for the coordination run.
- **repo**: repository owner/name.
- **pr_number**: PR number.
- **state**: INITIALIZED, RUNNING, PAUSED, COMPLETED, FAILED.
- **active_leases**: Map of `item_id -> LeaseRecord`.
- **queued_items**: Ordered list of `item_id` vended by the runtime.
- **retry_counts**: Map of `item_id -> int`. Incremented when an agent response fails parsing.

### WorkerPacket (Contract)
The thin JSON packet emitted by `orchestrate step`.
- **orchestration_run_id**: session run ID.
- **lease_token**: orchestrator-level lease token.
- **role_requested**: triage | fixer | verifier.
- **response_path**: absolute path where the agent MUST write its `ActionResponse`.
- **action_request**: The full authoritative `ActionRequest` object from the Runtime CLI.

## State Transitions

### Lease Acquisition
1. `orchestrate step` calls `workflow.issue_action_request`.
2. Core runtime creates a lease in `session.json`.
3. Orchestrator creates its own `LeaseRecord` in `orchestration.json`.
4. If either fails, the command fails loud.

### Evidence Submission
1. `orchestrate submit` reads the file at `response_path`.
2. Validates `files` and `note` (and other required evidence).
3. If parsing fails, increments `retry_counts[item_id]`.
4. If `retry_counts >= 3`, raises `HumanHandoffRequired` and halts.
5. If valid, calls `workflow.submit_action_response`.
6. Upon runtime success, releases the orchestrator lease.
