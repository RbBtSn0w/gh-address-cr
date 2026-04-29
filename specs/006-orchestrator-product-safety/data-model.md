# Data Model: Orchestrator Product Safety

This document outlines the updates to existing data models for feature 006.

## OrchestrationSession (orchestration.json)

The `OrchestrationSession` model is extended to include configuration parameters, completion locking, and human intervention state.

```json
{
  "run_id": "string",
  "repository": "owner/repo",
  "pr_number": 123,
  "config": {
    "max_concurrency": 3,
    "circuit_breaker_threshold": 3
  },
  "completed": false,
  "completed_at": "timestamp (optional)",
  "completed_reason": "string (optional)",
  "active_leases": {
    "finding-1": {
      "lease_token": "string",
      "worker_role": "fixer",
      "acquired_at": "timestamp",
      "retry_count": 0,
      "waiting_for_human": false,
      "handoff_reason": "string (optional)",
      "artifact_path": "string (optional)"
    }
  },
  "queued_items": ["finding-2"]
}
```

### Key Additions:
- `config`: Persists runner overrides for coordination guardrails.
- `completed`: The orchestration completion lock.
- `waiting_for_human`: Flag indicating a worker hit the circuit breaker limit for a specific item.
- `handoff_reason`: The specific error that triggered the handoff.
- `artifact_path`: The location of the failing payload for human inspection.
