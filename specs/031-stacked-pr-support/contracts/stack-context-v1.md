# Contract: `stack_context.v1`

## Machine Summary Additions

Existing required fields remain unchanged. PR-scoped high-level and final-gate
summaries add:

```json
{
  "completion_scope": "pull_request",
  "stack_context": {
    "schema_version": "stack_context.v1",
    "availability": "present",
    "observed_at": "2026-08-01T12:00:00Z",
    "topology_fingerprint": "sha256:...",
    "stack": {
      "number": 7,
      "trunk_ref_name": "main",
      "size": 3,
      "selected_position": 2,
      "members": [
        {
          "position": 1,
          "pr_number": "101",
          "state": "OPEN",
          "is_draft": false,
          "base_ref_name": "main",
          "head_ref_name": "feature/base",
          "head_oid": "full-oid",
          "merge_queue_state": null
        }
      ]
    }
  },
  "stack_merge_readiness": "not_evaluated"
}
```

`completion_scope` does not replace `gate_scope`:

- `gate_scope=inline`, `completion_scope=pull_request`: high-level pre-gate.
- `gate_scope=final`, `completion_scope=pull_request`: authoritative layer gate.
- `gate_scope=final`, `completion_scope=stack_segment`: aggregate gate.

## Availability Shapes

Unstacked uses `availability=absent` and selected PR facts without stack
identity. Capability failure uses `availability=unavailable` plus bounded
`STACK_CONTEXT_UNAVAILABLE` diagnostics. Invariant failure uses
`availability=invalid`, `STACK_CONTEXT_INVALID`, and a bounded invariant code.
Raw GraphQL response bodies are never embedded.

## Compatibility

- Fields are additive; unstacked calls keep current reason and exit codes.
- Callers may ignore `stack_context`, but completion guidance must inspect it
  before any stack-wide claim.
- `stack_context.v1` versions independently from ActionRequest `1.0`.
