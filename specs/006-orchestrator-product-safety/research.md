# Research: Orchestrator Product Safety & Convergence

**Feature**: 006-orchestrator-product-safety

## Decisions

### Coordination Guardrails Parameters
- **Decision**: Safe defaults are hardcoded in the control plane (`max_concurrency=3`, `circuit_breaker_threshold=3`). Overrides are allowed via CLI arguments or environment variables and MUST be persisted into `orchestration.json` (e.g., under a `config` key) upon session initialization or update.
- **Rationale**: Pure hardcoding lacks flexibility for different environments or runner capabilities. Pure configuration risks behavioral drift across resumes if the runner forgets to pass the flag. Persisting the overrides ensures the session remains deterministic and auditable.

### Human Intervention Recovery Path
- **Decision**: Introduce a visible `waiting_for_human: true` state in `orchestration.json` along with `handoff_reason` and `artifact_path`. Recovery requires manual repair of the artifact, followed by a normal `agent orchestrate submit` using the same `--item-id` and `--token`. A successful submit clears the human intervention state.
- **Rationale**: An "override flag" to forcefully resume can lead to silent bypasses of critical errors, violating the fail-fast principle. Making the state explicit and requiring a valid submission to progress ensures the recovery is deliberate and leaves an audit trail.

### Verified Lock Mechanism
- **Decision**: Implement an Orchestration Completion Lock entirely within `orchestration.json` (e.g., `completed: true`). The `start` and `step` commands will evaluate this lock against the authoritative core `session.json`. If locked and the core session has no new blocking/unhandled items, it returns `SESSION_LOCKED`. If the core session has new items, the lock is automatically cleared.
- **Rationale**: Modifying `session.json` with orchestrator-specific completion flags pollutes the core truth. Using `orchestration.json` keeps the coordination layer's lifecycle management separate while ensuring it safely reconciles with any out-of-band updates to the core session.

### Status-to-Action Convergence
- **Decision**: Ensure all non-zero exit paths or logical failure modes (e.g., parsing errors, stale leases) output a structured JSON containing a `reason_code` and `next_action`.
- **Rationale**: Essential for safe AI consumption. Runners should branch on explicit signals rather than parsing unstructured stderr output.

### SKILL.md Policy Enforcement
- **Decision**: Rewrite the orchestration section of `gh-address-cr/SKILL.md` to mandate that agents branch *only* on the machine summary reason codes and signals.
- **Rationale**: Enforces the "Thin Skill" and "Behavioral Policy Layer" principles, decoupling agent reasoning from control plane state transitions.
