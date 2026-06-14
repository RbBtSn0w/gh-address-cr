# Implementation Plan: Homogeneous Decline + Lean Aliases

Companion to `spec.md`. Implements a reject/clarify match-all shortcut symmetric
with the existing `fix` homogeneous path, plus stable lean aliases.

## Strategy

Generalize the existing fast-fix match-all machinery to carry a **resolution**
(`fix` | `reject` | `clarify`) rather than assuming `fix`. The match/route/claim/
submit pipeline is already correct; only three things are fix-specific today:

1. `_build_fast_fix_context` mandates `--commit` + `--validation` (decline needs
   neither).
2. `_build_fast_fix_batch_response` hardcodes `classification="fix"` and emits a
   `fix_reply`.
3. `_write_fast_fix_batch_file` writes a `common_fix_reply` with `commit_hash`.

Everything else (`_resolve_fast_fix_matches`, body-identity gate, stale routing,
chunked claim + `submit_batch_action_response`, partial-failure handling) is reused.

## Phase 1 — Workflow core (TDD)

Tests first (`tests/`), mirroring `014-fix-all-thread-replies` coverage:

- Homogeneous reject across N identical-body threads → all accepted, replies carry
  the shared rationale.
- Heterogeneous bodies → rejected, routed to per-thread batch skeleton.
- Decline path rejects `--commit`/validation as not-applicable, requires
  `--homogeneous-reason` + `--match-files`.
- Stale thread in set → stale route.
- Partial lease failure → `*_PARTIAL` with per-row failures.

Implementation in `core/workflow.py`:

- Add a `resolution: str = "fix"` parameter threaded through
  `fast_fix_matching_threads` → `_build_fast_fix_context` → `_process_fast_fix_matches`
  → `_build_fast_fix_batch_response` / `_write_fast_fix_batch_file`.
  Prefer a small `resolution` enum/Literal validated up front.
- In `_build_fast_fix_context`: when `resolution != "fix"`, skip the commit and
  validation requirements; keep files + homogeneous-reason required. Derive distinct
  status prefixes if useful (`DECLINE_ALL_*`) or reuse `FAST_FIX_ALL_*` — decide in
  contracts; reusing keeps protocol surface smaller.
- In `_build_fast_fix_batch_response`: set `classification=resolution`; for decline,
  emit `reply_markdown` + `note` from `homogeneous_reason` instead of `fix_reply`.
- Keep the `_has_homogeneous_thread_bodies` gate for **all** match-all resolutions
  (it already runs when `homogeneous_reason` is set — verify it also guards decline).
- `_enforce_fast_fix_routing`: keep stale routing; keep the "non-homogeneous →
  batch skeleton" branch (decline without a shared reason should also route to batch).

No change needed in `agent_protocol.submit_batch_action_response` — it already
accepts reject/clarify rows. Confirm `_validate_fix_all_input_item_reply_evidence`
is **not** on the homogeneous path (it guards `--batch --input`, which we are not
relaxing). The homogeneous path synthesizes per-item evidence, so that validator is
bypassed exactly as the fix homogeneous path bypasses it today.

## Phase 2 — CLI surface

`commands/agent.py` `handle_agent_resolve`:

- Add `--reject` / `--clarify` store_true flags (resolution selector).
- Extend the mutual-exclusion check (`selected_modes` at `agent.py:365-385`) so
  `--reject`/`--clarify` conflict with each other, with `--batch`/`--stale`/`--trivial`,
  and with the fix match-all path (`--commit` present) → `CONFLICTING_RESOLVE_MODE`.
- In `_dispatch_agent_resolve`, add a branch (before the `not item_id` fix branch)
  for decline match-all: require `--match-files` + `--homogeneous-reason`, no commit;
  call `workflow.fast_fix_matching_threads(..., resolution="reject"|"clarify")`.
- Extend the `item_id` + mode conflict guard (`agent.py:428`) to include the new
  flags.

## Phase 3 — Lean aliases

- In the session projection / lean rendering path (where `--lean` thread rows are
  built), assign deterministic per-session aliases (`T1…Tn`, ordered by file then
  thread creation) and include both `alias` and `item_id` in lean output.
- Add an alias→item_id resolver used by commands that accept `<item_id>`; resolve
  before lease/claim. Ambiguous/expired alias → actionable error pointing at `--lean`.
- Tests: alias stability within a session, alias accepted by `agent resolve <alias>`,
  stale-alias error after re-sync.

## Phase 4 — Templates, docs, surfacing

- `core/command_templates.py`: add a `resolve_decline_homogeneous` template and
  surface it where `resolve_homogeneous` is offered (`gate.py:346`,
  `command_templates.py:172`, and the high-level next-actions in
  `commands/high_level.py:470`).
- `core/command_templates.py` / `commands/common.py`: document the new flags
  (`--reject`, `--clarify`).
- Docs: `docs/cli-reference.md`, `docs/workflows.md`, and the skill `SKILL.md`/
  `skill/` instructions — add the decline shortcut and alias usage.
- `CHANGELOG.md` entry; this is additive (new flags) → minor version bump.

## Phase 5 — Verification & gates

- Run the repo quality gates (unittest + coverage ratchet — see
  `[[quality-gates-and-module-facades]]`). Keep thresholds green.
- Validate the `dist/` build sync if the skill ships a bundled CLI (the repo has a
  `dist/` + `cli-skill-sync` spec — confirm whether regeneration is required).
- Manual quickstart per `spec.md` §7 against a fixture session.

## Risk / decisions to lock before coding

- **Status-code reuse vs. new `DECLINE_ALL_*` prefix.** New prefixes are clearer in
  telemetry but expand the protocol surface and external-agent contract. Recommend
  reuse of `FAST_FIX_ALL_*` with `resolution` recorded in payload, unless telemetry
  consumers need to distinguish. Decide in `contracts/`.
- **Clarify semantics.** `clarify` keeps a thread open; confirm final-gate treats a
  homogeneous clarify as "answered" identically to a single clarify (R7).
- **Alias scope.** Ephemeral per-session index (recommended) vs. stable hash — see
  spec §8 open question.

## Touch list

- `src/gh_address_cr/core/workflow.py` (resolution param, context, batch row/file)
- `src/gh_address_cr/commands/agent.py` (flags, mode matrix, dispatch branch)
- `src/gh_address_cr/core/command_templates.py` (decline template)
- `src/gh_address_cr/core/gate.py`, `commands/high_level.py` (surface next-actions)
- `src/gh_address_cr/commands/common.py` (flag help)
- lean projection/rendering module (aliases) + alias resolver
- `tests/` (workflow, CLI, alias, publish)
- `docs/cli-reference.md`, `docs/workflows.md`, skill instructions, `CHANGELOG.md`
