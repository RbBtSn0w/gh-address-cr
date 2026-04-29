# Contract: Orchestrator-Runtime Link

## Command Delegations

| Orchestrate Command | Runtime Delegate Method | Authoritative Side Effect |
|---------------------|-------------------------|----------------------------|
| `start` | `session_engine.load_session` | None (reads only) |
| `step` | `workflow.issue_action_request` | Core lease creation in `session.json` |
| `submit` | `workflow.submit_action_response`| Core state transition (e.g. `OPEN` -> `FIXED`) |
| `stop` | `session_engine.cmd_gate` | None (Final gate validation) |
| `resume` | `session_engine.load_session` | None (re-syncs queue) |

## WorkerPacket Schema
The orchestrator emits this JSON on `step`:

```json
{
  "orchestration_run_id": "run-123",
  "lease_token": "lease-abc",
  "role_requested": "fixer",
  "response_path": "/path/to/response.json",
  "action_request": {
    "request_id": "req-456",
    "session_id": "owner__repo/pr-1",
    "lease_id": "core-lease-789",
    "agent_role": "fixer",
    "item": {
      "item_id": "local-finding:abc",
      "path": "src/main.py",
      "line": 10
    },
    "allowed_actions": ["fix", "clarify"],
    "required_evidence": ["files", "note"]
  }
}
```

## Exit Code Protocol
- **0**: Success. Task dispatched or session completed.
- **1**: Runtime error or invalid command usage.
- **2**: **Fail Loud** (Lease conflict, final-gate failure, or Human Handoff required).
- **5**: Unexpected internal error.
