# Lease Lifecycle Contract

- **Authority Boundary**: `session.json` is the sole authority for item status, findings, and GitHub state. `orchestration.json` ONLY holds volatile lease data and queue ordering.
- **Claim**: Orchestrator grants a lease via `WorkerPacket` and writes to `orchestration.json`.
- **Validation**: When submitting evidence, orchestrator verifies `lease_token` matches the active claim.
- **Expiration (TTL)**: Leases MUST include a specific TTL (e.g., 15 minutes). A step command can reclaim expired leases and re-queue items.
- **Expired Lease Handling**: If an agent submits a response using an expired lease token, the submission is rejected loudly.
- **Release**: Once an item is successfully submitted, published, or rejected by a verifier, the lease is explicitly released.