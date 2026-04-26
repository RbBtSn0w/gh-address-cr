# Lease Lifecycle Contract

- **Claim**: Orchestrator grants a lease via `WorkerPacket` and writes to `orchestration.json`.
- **Validation**: When submitting evidence, orchestrator verifies `lease_token` matches the active claim.
- **Expiration**: Leases include a TTL. A step command can reclaim expired leases and re-queue items.
- **Release**: Once an item is successfully submitted, published, or rejected by a verifier, the lease is explicitly released.