# Quickstart: Orchestrator Product Safety

This feature introduces crucial safety and stability mechanisms to the orchestrator.

## Overriding Guardrails

By default, the orchestrator uses safe limits (max concurrency 3, circuit breaker threshold 3). You can override these when starting or updating a session:

```bash
gh-address-cr agent orchestrate start owner/repo 123 \
  --max-concurrency 5 \
  --circuit-breaker-threshold 5
```

Alternatively, use environment variables:
```bash
export GH_ADDRESS_CR_ORCH_MAX_CONCURRENCY=5
export GH_ADDRESS_CR_ORCH_CIRCUIT_BREAKER_THRESHOLD=5
gh-address-cr agent orchestrate start owner/repo 123
```

These overrides are written to `orchestration.json` and will persist across resumes.

## Handling Human Intervention

If an agent fails repeatedly (e.g., generating invalid JSON), the orchestrator will hit the circuit breaker and enter a `HUMAN_INTERVENTION_REQUIRED` state for that specific lease.

1. **Observe the state**: The `orchestrate status` command will surface the blocked items.
2. **Inspect the artifact**: Check the `artifact_path` associated with the failing lease in `orchestration.json`.
3. **Manual Repair**: Fix the JSON payload manually.
4. **Resume Flow**: Submit the corrected payload using the *original* item ID and token. Do not use an override flag.
   ```bash
   gh-address-cr agent orchestrate submit owner/repo 123 \
     --item-id finding-1 \
     --token lease-xxx \
     --input repaired_response.json
   ```
   A successful submit clears the human intervention state.

## Session Lock

Once all items in the core `session.json` are resolved and `orchestrate stop` is called, the orchestrator sets a completion lock (`completed: true`) in `orchestration.json`.
Subsequent calls to `start` or `step` will return a `SESSION_LOCKED` status.

If external processes add new findings to `session.json`, the orchestrator will detect the discrepancy on the next `start` or `step`, automatically clear the lock, and resume processing.
