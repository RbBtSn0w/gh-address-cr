# Research: Remove Legacy Compatibility

## Decision: Remove script-dispatch compatibility from the runtime CLI

**Rationale**: The current runtime already exposes high-level native commands
for agent-safe workflows. Retaining a script-package dispatcher keeps an
obsolete compatibility decision in every unsupported-command path and preserves
historical command names as active behavior. Removing it makes unsupported usage
fail fast and reduces the active command surface to current contracts.

**Alternatives considered**:

- Keep the dispatcher and only hide it from help. Rejected because hidden
  compatibility shims remain active behavior and can silently preserve obsolete
  automation.
- Keep low-level command names as aliases to native modules. Rejected because
  aliases still create public compatibility obligations and confuse the
  Status-to-Action Map.

## Decision: Preserve current documented utility commands

**Rationale**: `review-to-findings`, `submit-feedback`, and `submit-action`
are documented as current utility commands in the runtime and packaged skill.
Removing them would break active workflows rather than historical compatibility.
They should remain available, but their implementation must not depend on the
historical script package.

**Alternatives considered**:

- Remove all non-high-level commands. Rejected because the spec scopes removal
  to unsupported legacy behavior, not active documented utility contracts.
- Treat utilities as legacy and require agents to use only `review`. Rejected
  because current skill guidance and tests rely on utility commands for
  producer conversion, feedback, and manual action submission.

## Decision: Mark retained historical references as archival

**Rationale**: Older specs explain why compatibility existed. Removing every
historical mention would reduce auditability, but leaving unmarked references
creates instruction drift. Retained historical references should clearly point
  to the 013 feature as the active authority for compatibility removal.

**Alternatives considered**:

- Rewrite all older specs in place. Rejected because it would erase historical
  context and create a large documentation churn unrelated to active behavior.
- Leave older specs untouched. Rejected because agents may treat them as
  current runnable instructions.
