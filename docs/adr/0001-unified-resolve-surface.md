# ADR 0001: Unified `agent resolve` surface

- Status: Accepted
- Date: 2026-06-13
- Issues: #126, #115, #123

## Context

The agent protocol exposed 7+ overlapping routes to resolve a single GitHub
review-thread fix: the granular `classify → next → submit → publish` four-step,
plus `agent fix`, `agent trivial-fix`, `agent fix-all --input`,
`agent fix-all --homogeneous-reason`, `agent submit-batch`, and
`agent resolve-stale`. Choosing between them required a dense prose paragraph in
`SKILL.md`, which contradicted the architecture guideline that "repeated feedback
that adds branches in the same design axis is a signal to update the architecture
spec instead of continuing to expand conditionals." The split also duplicated the
classification round-trip (#115) and dispersed publishing (#123).

## Decision

Collapse the mutating CLI surface into a single `agent resolve` command whose
mode is selected by flags, with route selection owned by the runtime:

- `resolve <item_id> …` — one straightforward thread fix
- `resolve <item_id> --trivial …` — documentation/typo-only fast path
- `resolve --batch --input <file>` — batch from a `BatchActionResponse`
- `resolve --commit … --homogeneous-reason <why>` — homogeneous repeated concern
- `resolve --commit … --stale --match-files` — STALE/outdated threads
- `resolve --commit …` with no `<item_id>` — match-all-by-files

Classification is recorded internally on this path, eliminating the
`MISSING_CLASSIFICATION` round-trip for the common case (#115). The granular
`classify`/`next`/`submit` commands remain as the low-level protocol that
`resolve` is built on. `agent publish` is the single canonical publish path; each
`resolve` mode also accepts `--publish` and reports `published` (#123).
`resolve --batch` routes through the stricter `fast_fix_from_batch_input` contract
(per-thread summary/why + stale-thread rejection).

The removed commands (`fix`, `trivial-fix`, `fix-all`, `resolve-stale`,
`submit-batch`) are deleted outright — this ships as a breaking major release with
no compatibility aliases.

## Consequences

- One decision point for agents; the disambiguation prose shrinks dramatically.
- `command_templates`, gate `commands{}` blocks, the manifest, and all skill/CLI
  docs now describe a single resolve surface.
- The obsolete `CONFLICTING_FIX_ALL_INPUT` guard is gone (`--batch` is
  unambiguous).
- Callers and tests that drove the old command strings were migrated in the same
  release.
