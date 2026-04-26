# Worker Packet Contract

The `WorkerPacket` is emitted by the orchestrator during `step`.

```json
{
  "orchestration_run_id": "run-xyz",
  "lease_token": "lease-abc",
  "role_requested": "fixer",
  "action_request": {
    "item_id": "finding-1",
    "item_kind": "local_finding",
    "allowed_actions": ["fix", "clarify", "defer"],
    "required_evidence": ["commit_hash", "files"]
  },
  "response_path": "/tmp/workspace/response-finding-1.json"
}
```

Workers must write their standard `ActionResponse` to the `response_path` and use the `lease_token` when interacting with the orchestrator.