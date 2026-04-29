# Contracts: Orchestrator Product Safety

## Status-to-Action Convergence

The Orchestrator's standard JSON response contract is expanded to support explicit "Next Action" signals for the AI runner, mapping internal reasons to definitive behavioral commands.

### Updated Machine Summary Structure

```json
{
  "status": "string (SUCCESS | WAITING | FAILED | LOCKED | DISPATCHED)",
  "reason_code": "string (e.g., HUMAN_INTERVENTION_REQUIRED, SESSION_LOCKED, STALE_QUEUE)",
  "message": "string (human readable)",
  "next_action": "string (PROCEED | RETRY | HALT | HANDOFF)"
}
```

### Signal Definitions

| `status` | `reason_code` | `next_action` | Expected Runner Behavior |
|----------|---------------|---------------|--------------------------|
| `FAILED` | `HUMAN_INTERVENTION_REQUIRED` | `HANDOFF` | Stop executing. Alert user. Provide the item ID and handoff reason. Wait for manual intervention. |
| `LOCKED` | `SESSION_LOCKED` | `HALT` | Stop executing. The PR is fully handled and locked. No further tasks are available. |
| `WAITING` | `MAX_CONCURRENCY_REACHED` | `RETRY` (with backoff) | Sleep. Re-poll using `status` or `step` later. |
| `WAITING` | `WAITING_FOR_LEASES` | `RETRY` (with backoff) | Sleep. The queue is empty but active leases exist. |
| `FAILED` | `PAYLOAD_CORRUPT` | `RETRY` | The submitted payload was invalid. The runner should retry generating the payload up to the threshold. |
| `DISPATCHED` | `NEW_TASK` | `PROCEED` | A new task was acquired. Runner should begin execution based on the returned `WorkerPacket`. |
| `SUCCESS` | `SUBMITTED` | `PROCEED` | A submission was accepted. The runner is free to request the next task. |

This mapping is authoritative. AI runners MUST NOT derive branching logic by parsing the `message` string.
