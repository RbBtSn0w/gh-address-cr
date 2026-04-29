# Research: Thin Skill Orchestration

## Decision: Keep the first-read skill as a thin adapter

**Decision**: The packaged skill entrypoint should be shortened around three duties: invoke the high-level runtime, interpret structured machine summaries, and enforce final-gate discipline.

**Rationale**: The runtime native refactor made deterministic code the control plane. Keeping long manual ladders in the first-read skill would recreate the old Markdown-driven workflow risk and create duplicate authority.

**Alternatives considered**:

- Keep the current long skill entrypoint and add more multi-agent details. Rejected because it increases prompt drift and makes the skill look like the workflow implementation.
- Move all guidance to advanced references. Rejected because first-time agents still need a small safe entry contract.

## Decision: Model adapter behavior as status-to-action mapping

**Decision**: The adapter should explain runtime outcomes through a status-to-action contract keyed by stable machine summary fields such as `status`, `reason_code`, `waiting_on`, `next_action`, and artifact paths.

**Rationale**: Agents should not parse prose or infer next steps from scattered documentation. A mapping contract is testable, concise, and keeps the runtime authoritative.

**Alternatives considered**:

- Let the agent read human text and decide. Rejected because it is not deterministic or testable.
- Add a second adapter-owned state machine. Rejected because it violates control-plane ownership.

## Decision: Runtime machine summary is the status source of truth

**Decision**: The `StatusActionMap` is derived from the runtime machine summary contract. The skill adapter may explain the mapping, but it must not invent statuses, infer hidden transitions, or persist an adapter-owned state machine.

**Rationale**: A thin adapter is only safe if status authority remains in the runtime. If the skill derives new states, it becomes a second control plane and can drift from final-gate and lease rules.

**Alternatives considered**:

- Let the adapter normalize runtime summaries into its own lifecycle. Rejected because it creates duplicate state ownership.
- Treat `next_action` prose as the full contract. Rejected because prose is guidance, not a versioned status taxonomy.

## Decision: Multi-agent orchestration is contract-first, runner-later

**Decision**: This feature defines role boundaries, capability checks, leases, action requests, action responses, evidence requirements, and runbooks, but does not ship a full autonomous runner as a requirement.

**Rationale**: A runner should consume a stable contract after the adapter and coordination semantics are validated. Shipping a runner too early would create a new coupling point and could hide state transitions outside the runtime.

**Alternatives considered**:

- Build `gh-address-cr-agent` immediately. Rejected for this stage because it combines contract design with scheduling and spawning policy.
- Keep orchestration entirely informal. Rejected because multi-agent work needs explicit lease and evidence boundaries.

## Decision: Keep review producers replaceable through normalized findings

**Decision**: External review production remains out of scope for this feature. Any producer may participate if it emits normalized findings or the accepted fixed `finding` block format.

**Rationale**: The project is a PR review resolution control plane, not a review engine. A stable intake contract lets Codex, Claude, CI, or other tools feed the same workflow without coupling the product to one producer.

**Alternatives considered**:

- Add a built-in review generator. Rejected because it expands the product into review production.
- Accept arbitrary narrative review prose. Rejected because the existing contract forbids narrative-only findings ingestion and would weaken fail-fast behavior.

## Decision: Validate documentation boundaries with executable tests

**Decision**: Repository docs, packaged skill docs, advanced references, and assistant hints should be checked for ownership claims, path-scope language, completion semantics, and low-level script exposure.

**Rationale**: This repository ships documentation as product behavior. Contract drift in `README.md` or `gh-address-cr/SKILL.md` can change agent behavior as much as code.

**Alternatives considered**:

- Rely on human review only. Rejected because path-scope and completion-rule regressions are easy to miss.
- Move all documentation into one file. Rejected because repo-level and packaged-skill scopes are intentionally different.

## Decision: Completion remains final-gate backed

**Decision**: Multi-agent orchestration must not change completion semantics. A completion claim still requires reply evidence, resolved GitHub thread state, no pending current-login review, no blocking local items, validation evidence, and final-gate success.

**Rationale**: The final gate is the authority that prevents false completion claims. Multi-agent participation increases the need for this gate rather than reducing it.

**Alternatives considered**:

- Let a verifier agent mark completion. Rejected because verifier output is evidence, not final authority.
- Allow manual completion claims for docs-only cases. Rejected because this product specifically governs PR review resolution sessions.
