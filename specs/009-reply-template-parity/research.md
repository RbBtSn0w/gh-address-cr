# Research: Reply Template Parity

## Decision: Runtime renderer is authoritative

**Rationale**: The constitution requires deterministic runtime code to own GitHub side effects. Reply body generation is part of the publish side effect, so it belongs under `src/gh_address_cr/core`.

**Alternatives considered**: Reading `skill/assets` at runtime would mirror the packaged files directly but would make the skill payload an implementation dependency.

## Decision: Preserve ActionResponse fields

**Rationale**: The existing protocol already separates `fix_reply` for fixes from `reply_markdown` for clarify/defer. The bug is output rendering drift, not schema insufficiency.

**Alternatives considered**: Adding structured clarify/defer schemas would be heavier and would create unnecessary protocol churn.

## Decision: Parity tests over code generation

**Rationale**: The smallest durable fix is to test runtime output, skill script output, and template asset headings together. Introducing a generator for assets would add maintenance cost without changing runtime behavior.

**Alternatives considered**: Generating all assets from Python constants was rejected for this bugfix because it expands the build process.
