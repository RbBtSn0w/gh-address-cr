# Contract: Lease Recovery Outcomes

## Purpose

Make lease expiration and stale submission recovery actionable for agents without weakening lease ownership or runtime truth.

## Recovery Outcome Shape

```json
{
  "status": "LEASE_RECOVERY_REQUIRED",
  "reason_code": "EXPIRED_LEASE_RECLAIMABLE",
  "lease_id": "lease_123",
  "request_id": "req_123",
  "item_id": "github-thread:THREAD_ID",
  "recovery_outcome": "reclaim",
  "next_action": "gh-address-cr agent reclaim owner/repo 123",
  "resume_command": "gh-address-cr agent next owner/repo 123 --role fixer --agent-id codex-fixer-1"
}
```

## Recovery Outcomes

| Outcome | Meaning | Agent Behavior |
|---------|---------|----------------|
| `renew` | Current agent still owns eligible work and can extend the lease. | Renew or resubmit through the provided command. |
| `reclaim` | Lease expired, but work item remains eligible for the same or a new claim. | Reclaim or request a fresh action request before submitting. |
| `refresh_state` | Request context is stale or insufficient. | Re-read session state and request a new next action. |
| `stop` | Work is no longer safe to mutate from this request. | Stop submitting and report the terminal reason. |
| `already_completed` | Runtime truth shows the item is already complete. | Do not submit; proceed to publish/final-gate flow if instructed. |

## Required Behavior

- Expired or stale submissions cannot overwrite changed work item state.
- Wrong agent, wrong role, wrong item, stale request hash, or changed evidence requirements must return a safe next action or stop reason.
- Lease events remain auditable across renew, reclaim, refresh, stop, and completion paths.
- Recovery reason codes are additive public machine-readable fields and must be covered by tests.
