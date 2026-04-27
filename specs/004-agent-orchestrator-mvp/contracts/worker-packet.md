# Worker Packet Contract

The `WorkerPacket` is emitted by the orchestrator during `step`. It MUST be kept as thin as possible. It MUST NOT include the entire session, all active leases, or other agent states.

```json
{
  "orchestration_run_id": "run-xyz",
  "lease_token": "lease-abc",
  "role_requested": "fixer",
  "action_request": {
    "item_id": "finding-1",
    "item_kind": "local_finding",
    "allowed_actions": ["fix", "clarify", "defer"],
    "required_evidence": ["changed_files", "validation_commands", "terminal_note", "reply_markdown", "github_reply_url", "final_gate_output"],
    "relevant_file_context": "src/example.py:10-20",
    "submit_recovery_instruction": "Run validation commands to verify your fix. Write the response JSON strictly to the response_path."
  },
  "response_path": "/tmp/workspace/response-finding-1.json"
}
```

Workers must write their standard `ActionResponse` to the `response_path` and use the `lease_token` when interacting with the orchestrator.