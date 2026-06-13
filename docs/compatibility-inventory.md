# Compatibility Inventory

This inventory separates supported compatibility contracts from historical
implementation names. Keep compatibility behavior explicit, tested, and scoped.

## Preserved Public Contracts

- `--machine` remains a compatibility alias for the default machine-readable
  output mode.
- Unsupported historical root commands such as `cr-loop`, `session-engine`,
  `clean-state`, `control-plane`, and `mark-handled` fail fast with
  unsupported-command guidance and must not mutate session state.
- `submit-action` accepts older loop-request artifacts with top-level `repo`
  and `pr_number`, while runtime `ActionRequest` artifacts use
  `repository_context.repo` and `repository_context.pr_number`.
- Historical GitHub thread data may include outdated or legacy-shaped fields.
  Runtime normalization keeps those readable while preserving current session
  and final-gate contracts.
- Existing Markdown decision blocks remain compatibility guidance. Structured
  `workflow_decision.v1` JSON is the preferred machine contract.

## Removed Or Unsupported Surfaces

- Installed runtime packages must not include `legacy_scripts` or
  `legacy_handlers`.
- Direct script-path command dispatch is unsupported; public commands route
  through the native runtime package.
- Narrative-only review ingestion is unsupported; producer output must be
  findings JSON or fixed `finding` blocks.
- As of 3.0, the `agent fix`, `agent trivial-fix`, `agent fix-all`,
  `agent resolve-stale`, and `agent submit-batch` commands are removed with no
  compatibility alias. All mutating resolution routes through `agent resolve`
  (with `--trivial`, `--batch --input`, `--homogeneous-reason`, or
  `--stale --match-files`). Unknown-command guidance is returned for the removed
  names. See [migration-3.0.md](migration-3.0.md).

## Internal Naming Rule

Use `legacy` in code only when the behavior is explicitly about a preserved
public compatibility contract or an unsupported historical command. Prefer
domain names such as `loop_request`, `outdated_thread`, `compatibility_alias`,
or `unsupported_historical_command` when describing current implementation
paths.

