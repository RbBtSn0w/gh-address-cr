# Contract: Adapter Boundary

## Purpose

Define what belongs in the packaged skill adapter versus the deterministic runtime and repository-level support files.

## Ownership Matrix

| Concern | Owner |
| --- | --- |
| Session state transitions | Runtime |
| GitHub replies and resolves | Runtime |
| Claim leases and conflict detection | Runtime |
| Evidence acceptance and ledger writes | Runtime |
| Final-gate evaluation | Runtime |
| Public command routing | Skill adapter |
| Status interpretation guidance | Skill adapter |
| Advanced usage references | Skill adapter |
| Assistant-specific hints | Skill adapter |
| Tests and CI | Repository root |
| Release metadata | Repository root |

## Packaged Skill Rules

- The first-read skill entrypoint must identify itself as an adapter.
- The default workflow must route through the high-level runtime command.
- Skill-owned docs use paths relative to the installed skill root, such as `scripts/cli.py`, `references/...`, and `agents/openai.yaml`.
- Advanced references may explain detailed behavior but must not become alternate runtime implementations.
- Low-level scripts must not be presented as agent-safe public APIs.

## Repository Rules

- Repo-level docs use repo-root paths such as `gh-address-cr/SKILL.md` and `gh-address-cr/scripts/cli.py`.
- Tests own executable validation of documentation contracts.
- README may explain architecture and release behavior but must stay aligned with packaged skill guidance.

## Fail-Fast Rules

- Missing runtime blocks execution before session mutation.
- Incompatible runtime blocks execution before session mutation.
- Documentation contradictions between runtime authority and skill authority are validation failures.
- Direct agent side-effect attempts are invalid.

## Test Expectations

- Tests scan packaged skill docs for repo-root path leakage.
- Tests scan public docs for low-level script promotion as agent-safe APIs.
- Tests assert final-gate remains the only completion authority.
- Tests assert runtime ownership claims are consistent across README, SKILL, references, and assistant hints.
