---

description: "Task list for Resolve Command Orthogonalization"

---

# Tasks: Resolve Command Orthogonalization

**Input**: Design documents from `specs/029-resolve-orthogonalization/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md (all present)

**Tests**: Included — this changes public CLI/agent contracts (3 commands),
reason codes, and the Status-to-Action Map, which require contract/regression
tests per the constitution's Testable Contracts rule.

**Organization**: Tasks are grouped by user story (US1/US2/US3, matching
spec.md priorities P1/P2/P3).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 (close #204, single-item decline incl. stale), US2 (kill the
  matrix / full axis composability), US3 (converge + backward compat + vocab
  alignment across 3 commands)

## Path Conventions

Single project. Runtime: `src/gh_address_cr/`. Tests: `tests/` (repo root).
Packaged skill docs: `skill/` (thin adapter — descriptive only, no logic).

---

## Phase 1: Setup

**Purpose**: Confirm the working baseline before touching the resolve surface.

- [X] T001 Run `pip install -e .`, `python3 -m unittest discover -s tests`, and
  `ruff check src tests scripts/build_plugin_payload.py` to confirm a green
  baseline before any change (no file changes; record baseline pass count).
- [X] T002 [P] Read current behavior end-to-end: `python3 -m gh_address_cr
  agent resolve --help` and `python3 -m gh_address_cr submit-action --help`
  output captured as a baseline snapshot (no file changes; used to diff against
  post-change help output for SC-004/SC-006).

**Checkpoint**: Baseline confirmed green; no code changed yet.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the shared axis model, canonical vocabulary source, and
new reason codes that every user story routes through. **No user story work
starts before this phase is complete.**

**⚠️ CRITICAL**: `agent resolve` dispatch changes in US1–US3 all depend on the
validator and vocabulary constant created here.

- [X] T003 **Consolidate** the disposition vocabulary onto one true source
  (widened per R-3 correction — `/speckit-analyze` found this set was
  independently defined in **three** places, not one). Keep
  `src/gh_address_cr/agent/roles.py::TERMINAL_RESOLUTIONS =
  frozenset({"fix", "clarify", "defer", "reject"})` as the single source of
  truth (it is already the common import root for `core/models.py`,
  `agent/responses.py`, `agent/requests.py`, `agent/manifests.py`). Change:
  (a) `src/gh_address_cr/core/agent_protocol_evidence.py::TERMINAL_RESOLUTIONS`
  (used by `record_classification` in `core/agent_protocol.py`) to import/alias
  `agent.roles.TERMINAL_RESOLUTIONS` instead of independently defining an equal
  literal; (b) `src/gh_address_cr/agent/responses.py::WORKFLOW_DECISIONS`
  (used by `validate_workflow_decision` for the `workflow_decision.v1` schema)
  likewise. Export the single source for reuse by `commands/agent.py` and
  `commands/submit_action.py` dispatch/validation code (data-model.md Entity 2,
  research.md R-3 correction).
- [X] T004 [P] Add new reason codes `RESOLVE_AXIS_CONFLICT`,
  `RESOLVE_EVIDENCE_INCOHERENT`, `RESOLVE_FLAG_DEPRECATED` as centralized
  constants in `src/gh_address_cr/core/protocol_codes.py` (verified: the
  convention is **mixed**, not inline-only — `commands/agent.py` already
  imports `protocol_codes.FAST_FIX_REJECTED` and
  `protocol_codes.MISSING_FIX_REPLY_COMMIT_HASH` alongside inline literals
  like `"CONFLICTING_RESOLVE_MODE"`; new resolve-path codes follow the
  centralized precedent). **Do not** reuse the existing
  `protocol_codes.DEPRECATION_WINDOW_OPEN` constant for T028/T031's
  window-open signal — investigated and rejected: it was added in an
  unrelated feature (#179, deterministic rollout/consolidation policy), is
  never consumed anywhere in the codebase today, and belongs to that
  rollout-policy domain's vocabulary, not the resolve-command deprecation
  mechanism; reusing it would be a false cross-domain coupling, not genuine
  reuse (see research.md R-7).
- [X] T005 Implement the axis-coherence validator
  `_validate_resolve_axes(parsed: argparse.Namespace) -> None` in
  `src/gh_address_cr/commands/agent.py`, replacing (not wrapping) **both**
  of the current pairwise-exclusion gates:
  (a) the inline `selected_modes` mutual-exclusivity check inside
  `handle_agent_resolve` (lines ~382–404) that raises `CONFLICTING_RESOLVE_MODE`
  whenever ≥2 of `{--batch/--input, --trivial, --stale, --reject, --clarify}`
  are simultaneously true — **this is the gate that currently blocks the
  target `<item_id> --stale --clarify` combination**, because it treats
  `--stale` (a condition-axis value) and `--clarify` (a disposition-axis
  value) as two "modes" in the same flat list, even though they are on
  different axes and must compose; and
  (b) the `_validate_resolve_mode` function's `ITEM_ID_NOT_ALLOWED_FOR_MODE`
  block (lines ~445–457).
  New validator rules (data-model.md): same-axis conflict (two selection
  sources, e.g. `item_id` **and** `--files`/`--input`; or two disposition
  flags, e.g. `--reject` **and** `--clarify` together) → `RESOLVE_AXIS_CONFLICT`;
  fix-only evidence (`--commit`/`--validation`) with a decline disposition
  (`--reject`/`--clarify`) → `RESOLVE_EVIDENCE_INCOHERENT`. It MUST NOT reject
  any valid cross-axis combination, explicitly including `item_id` + `--stale`
  + `--reject`/`--clarify` (C-A1, C-A2, C-A3, C-A4).
- [X] T006 [P] Scaffold `tests/contract/test_resolve_axes_contract.py` with the
  enumerated (disposition × selection × condition) product fixture (helper that
  builds argv for each cell) — no assertions yet, just the enumeration and a
  `TODO` marker per cell category (valid cross-axis / same-axis conflict /
  incoherent evidence), to be filled in by US1/US2 tasks.
- [X] T007 [P] Scaffold `tests/test_disposition_vocabulary.py` importing
  `TERMINAL_RESOLUTIONS` and asserting it is non-empty and contains exactly
  `{"fix", "clarify", "defer", "reject"}` (baseline assertion; cross-command
  assertions added in US3).

**Checkpoint**: Axis vocabulary confirmed, new reason codes defined, validator
skeleton in place, contract test scaffolds ready. User story implementation
can now begin.

---

## Phase 3: User Story 1 - Decline one specific review thread, including when it is stale (Priority: P1) 🎯 MVP

**Goal**: Close issue #204 — an agent can `agent resolve <item_id>
--disposition reject|clarify --why <reason>` for exactly one thread, fresh or
stale, with no mode-preset rejection.

**Independent Test**: Take a PR with one open thread and one stale thread.
Decline each individually by `item_id`; confirm a reply is recorded and each
reaches terminal declined state, with no `ITEM_ID_NOT_ALLOWED_FOR_MODE` /
`CONFLICTING_RESOLVE_MODE`.

### Tests for User Story 1

> Write these tests FIRST; confirm they FAIL against current `agent resolve`
> before implementing.

- [X] T008 [P] [US1] Contract test: single-item `--disposition reject` on a
  **fresh** thread resolves that one thread with reply+resolve evidence and no
  mode error, in `tests/contract/test_resolve_axes_contract.py` (fills the
  (single × reject × fresh) cell from T006). Drive it through the **actual
  CLI dispatch** (`handle_agent_resolve` / `agent.main(argv)`), not by calling
  `_validate_resolve_mode` or `_validate_resolve_axes` directly — the bug this
  story fixes lives in the outer `selected_modes` gate (T005), which a
  validator-only unit test would not exercise. (The legacy `--reject` boolean
  form is separately covered by T024's deprecation-alias tests, not here.)
- [X] T009 [P] [US1] Contract test: single-item `--disposition clarify` on a
  **stale** thread (`item_id` + `--stale`, no `--match-files`) resolves that
  one thread with no mode error, in `tests/contract/test_resolve_axes_contract.py`
  (fills (single × clarify × stale) — the previously-blocked cell, R-1/C-A2).
  **Must** invoke the full CLI dispatch with argv `[repo, pr, item_id,
  "--disposition", "clarify", "--stale", "--why", ...]` end-to-end (same
  rationale as T008 — this is exactly the combination the `selected_modes`
  list in `handle_agent_resolve` rejects today via `CONFLICTING_RESOLVE_MODE`,
  before `_validate_resolve_mode` or `_dispatch_agent_resolve` ever run). Use
  the `stale_github_thread_item()` fixture pattern from
  `tests/test_native_workflow.py::StaleThreadClaimabilityTests`.
- [X] T010 [P] [US1] Regression test in `tests/test_agent_resolve_guards.py`:
  `agent resolve <item_id> --disposition reject --why <text>` and
  `agent resolve <item_id> --disposition clarify --stale --why <text>` are
  **accepted** through the full CLI entrypoint (replacing/removing the current
  `test_item_id_with_batch_or_stale_is_rejected` assertions that treat these as
  errors — batch/`--input` conflicts remain errors, but
  `--stale`/`--disposition reject`/`--disposition clarify` with a single
  `item_id` do not). Include an explicit case for `--stale` +
  `--disposition clarify` together (the `selected_modes` false-conflict case),
  not just each flag individually. Also assert the legacy boolean spellings
  (`--reject`, `--clarify`) still work equivalently per T015's MVP
  normalization (visible-deprecation-notice assertion itself is T024's job,
  not this task's). **And assert the missing-reason case** (found by
  `/speckit-analyze` U1): `agent resolve <item_id> --disposition reject` with
  **no** `--why` (and no deprecated `--homogeneous-reason` alias) →
  `MISSING_RESOLVE_ARGS` with a decline-specific message, not a silent
  no-reason submission (a decline requires a reason, Principle III;
  data-model validation rules).
- [X] T011 [US1] Automated final-gate **and lease-ownership** test for the
  **decline** path (fresh and stale) in `tests/test_native_workflow.py` or
  `tests/contract/test_resolve_axes_contract.py`:
  (a) drive a single-item `reject`/`clarify` resolution through `agent publish`
  → `final-gate` and assert PASS, following the same pattern as
  `test_stale_thread_classify_submit_publish_final_gate_path` (which only
  covers `classification="fix"` today — verified by reading its body). This
  closes the FR-009 gap where final-gate authority for the new decline path
  was previously only exercised manually via quickstart, not by an automated
  contract/unit test.
  (b) Assert lease-ownership semantics hold identically for decline: attempt a
  second agent's `decline_item(...)` (T012) on an item already leased by a
  first agent and confirm it surfaces `LEASE_LOCKED_ITEM`/lease-recovery
  behavior the same way `fast_fix_item` does — verified structurally correct
  because `decline_item` (T012) composes the same disposition-agnostic
  `agent_protocol.issue_action_request(role="fixer", ...)` lease primitive
  used by `fast_fix_item` (the primitive acquires a lease before any
  resolution type is known), so this assertion documents and locks in that
  inherited guarantee (FR-009) rather than leaving it implicit.

### Implementation for User Story 1

- [X] T012 [US1] Add a single-item decline function
  `decline_item(*, repo, pr_number, item_id, agent_id, resolution, why,
  publish, now) -> dict` in `src/gh_address_cr/core/workflow.py` (near
  `fast_fix_item`/`trivial_fix_item`, ~line 587), implemented by composing the
  **existing** primitives: `agent_protocol.record_classification(...,
  classification=resolution)` → `agent_protocol.issue_action_request(role=
  "fixer", ...)` (or the equivalent single-item lease call already used by
  `fast_fix_item`) → `agent_protocol.apply_response_to_item(...)` with
  `resolution` and `note=why` → optional publish. No new algorithm — mirrors
  the flow already proven by
  `test_stale_thread_classify_submit_publish_final_gate_path`. **`why` is
  required**: raise `MISSING_RESOLVE_ARGS` (decline-specific message) if empty,
  since `record_classification` already requires a non-empty note and a
  decline must carry a reason (U1; Principle III).
- [X] T013 [US1] **Restructure `_dispatch_agent_resolve` (~line 598) to route
  on SELECTION first, disposition/condition second** — this is the actual fix
  for the flagship #204 scenario, found missing by `/speckit-analyze` (U1):
  today's router checks `if parsed.reject or parsed.clarify: return
  _dispatch_decline_resolution(...)` and `if parsed.stale: return
  _dispatch_stale_resolution(...)` **before** ever checking `parsed.item_id`
  (lines 600, 617) — so `<item_id> --disposition clarify --stale` (T009) would
  still be caught by the `--stale` branch and routed into the **collective**,
  `--commit`-requiring stale path, never reaching the single-item decline
  wiring, even after T012/T014/T015 land. Reorder to:
  `if parsed.item_id: return _dispatch_single_item_resolution(parsed,
  disposition=disposition, now_dt=now_dt)` **first**, then batch, then the
  files-scope collective branches (decline/stale/fix) keyed on `disposition`
  read from the normalized value (T015) — never on raw
  `parsed.reject`/`parsed.clarify`/`parsed.stale` booleans directly for
  routing purposes. Update `_dispatch_single_item_resolution` (~line 558) to
  accept/compute `disposition` and route `reject`/`clarify` to the new
  `workflow.decline_item(...)` (requiring `--why`, not
  `--commit`/`--files`/`--summary`), while fix/trivial keep routing to
  `fast_fix_item`/`trivial_fix_item` unchanged.
- [X] T014 [US1] Remove **both** legacy exclusivity gates identified in T005,
  **and explicitly wire the replacement validator into the call site** (closes
  the `/speckit-analyze` U-1(prior) gap — T005 only *defines*
  `_validate_resolve_axes`; this task is what actually calls it):
  (a) delete the inline `selected_modes` mutual-exclusivity check in
  `handle_agent_resolve` (lines ~382–404) — this is the gate that actually
  fires on `--stale --clarify`/`--stale --reject` today and must stop treating
  condition-axis (`--stale`) and disposition-axis (`--reject`/`--clarify`)
  flags as competing "modes"; (b) delete the `_validate_resolve_mode` block
  that raises `ITEM_ID_NOT_ALLOWED_FOR_MODE` for `parsed.stale or
  parsed.reject or parsed.clarify` (lines ~445–457); (c) **call
  `_validate_resolve_axes(parsed)` from `handle_agent_resolve`** in place of
  both removed gates, before dispatch — this explicit call-site wiring is the
  step that was previously only implied by T005's docstring language. This
  task and T013 are tightly coupled (both touch the same dispatch region) and
  should land together. Keep exclusivity checks only for genuinely same-axis
  conflicts (two selection sources, e.g. batch/`--input` with `item_id`; two
  dispositions — now structurally impossible to specify twice once T015 makes
  disposition a single enum flag, so this reduces to validating
  `--disposition` is a legal choices value plus the legacy-alias-conflict case
  from T017/T020).
- [X] T015 [US1] Add the disposition axis as a **single enum flag**
  `--disposition {fix,trivial,reject,clarify}` (default `fix`) to the `agent
  resolve` argparse definition in `src/gh_address_cr/commands/agent.py`
  (~lines 340–376), mirroring `submit_action.py`'s existing `--resolution`
  flag exactly (R-4 correction — this is required for SC-004's ≤3 count; see
  contracts/resolve-axes-cli.md C-A1/C-A9). For this MVP story, normalize
  disposition from either the new `--disposition` flag or the legacy
  `--trivial`/`--reject`/`--clarify` booleans (both keep working; the
  *visible* deprecation notice for the legacy form is added later in T028,
  not required to close #204). Also wire `--stale` as an independent boolean
  available alongside `item_id` (not gated behind `--match-files`).
- [X] T016 [US1] Run T008–T011 and confirm they pass; run
  `python3 -m unittest discover -s tests` for regressions in
  `fast_fix_item`/`trivial_fix_item`/batch paths untouched by this story.

**Checkpoint**: Issue #204 is closed — single-item decline (fresh and stale)
works end-to-end and is independently testable/demoable.

---

## Phase 4: User Story 2 - Compose any disposition with any selection and condition (Priority: P2)

**Goal**: Eliminate the emergent conflict matrix — every valid cross-axis
combination is reachable; only same-axis conflicts and incoherent
disposition/evidence pairings fail, with one directive error each.

**Independent Test**: Enumerate the full disposition × selection × condition
product; every valid cell resolves via the expected primitive; every invalid
cell yields exactly one directive reason code.

### Tests for User Story 2

- [X] T017 [P] [US2] Complete the enumerated product in
  `tests/contract/test_resolve_axes_contract.py` (T006 scaffold): every valid
  cross-axis cell (files+`--disposition reject`+stale,
  files+`--disposition fix`+stale, files+`--disposition clarify`+fresh,
  **single+`--disposition trivial`+stale** (FR-003 is exhaustive over all four
  dispositions including `trivial`, found by `/speckit-analyze` U1 — do not
  silently skip this cell the way the routing table's `single | fix / trivial
  | fresh or stale` row already correctly covers it), batch+mixed, etc.)
  asserts success — **use `--why` as the decline reason for EVERY selection,
  single and files** (reason-flag unification, data-model Entity 1; supersedes
  a prior round's `--homogeneous-reason`-for-files guidance, which created the
  deprecated-vs-live contradiction now resolved — T021 wires
  `_dispatch_decline_resolution` to read the reason from `--why`); two
  same-axis values assert
  `RESOLVE_AXIS_CONFLICT` — for selection: `item_id` + `--files` at once; for
  disposition: **two legacy booleans together** (`--reject` + `--clarify`, both
  still accepted as deprecated aliases during the window per T028) **or** a
  legacy boolean disagreeing with `--disposition` (e.g. `--disposition fix
  --reject`) — both normalize to "disposition resolves to more than one
  value" and must be rejected the same way a directly-conflicting
  `--disposition` choice would be (argparse's `choices` already prevents
  picking two enum values in one flag, so this case only arises via
  legacy-alias interaction). Fix evidence + decline disposition asserts
  `RESOLVE_EVIDENCE_INCOHERENT` (C-A1, C-A3, C-A4).
  **Additional cases found by `/speckit-analyze`**:
  (F1) `--files src/a.py --disposition reject --why x` (and the stale
  equivalent) succeeds **without** `--match-files` — regression-guards T021's
  gate removal; a pre-fix run of this case would show `MISSING_MATCH_FILES`.
  (F2) `--disposition trivial` combined with `--files`/`--input` (no
  `item_id`) is an **intentional, retained** cross-axis exclusion — asserts
  `TRIVIAL_REQUIRES_ITEM_ID` (the existing, un-deleted check in
  `_validate_resolve_mode`, lines ~437–444), not `RESOLVE_AXIS_CONFLICT` and
  not silent success — this is documented as the one stated exception to
  C-A1's "no cross-axis exclusion" claim.
  (U2-dissolved) `<item_id> --disposition reject --homogeneous-reason x`
  succeeds as a single decline whose reason came via the deprecated alias
  (emits deprecation notice, T028) — asserts success + notice, **not** an axis
  conflict (reason-flag unification; there is no special `item_id +
  --homogeneous-reason` conflict rule).
- [X] T018 [P] [US2] Test in `tests/test_agent_resolve_guards.py` that a fix
  disposition missing required evidence still returns the **existing** codes
  unchanged: `MISSING_RESOLVE_ARGS` (single) / `MISSING_FIX_REPLY_COMMIT_HASH`
  (collective) — proving C-A4's "preserved, not renamed" clause.
- [X] T019 [P] [US2] Discoverability test: `python3 -m gh_address_cr agent
  resolve --help` output (captured via subprocess or argparse
  `format_help()`) contains the three axis parameter names and does **not**
  enumerate mode-preset flags as the primary documented path (SC-006), in
  `tests/test_skill_docs.py` or a new `tests/test_agent_resolve_help.py`.

### Implementation for User Story 2

- [X] T020 [US2] Extend `_validate_resolve_axes` (from T005) in
  `src/gh_address_cr/commands/agent.py` to cover all same-axis conflicts
  identified in T017: two selections (`item_id` + `--files`/`--input`), and
  disposition resolving to more than one value after legacy-alias
  normalization (T015/T028) — two legacy booleans set together, or a legacy
  boolean disagreeing with an explicit `--disposition` — plus the
  disposition/evidence incoherence check. Replaces any remaining pairwise
  checks from the old `_validate_resolve_mode`.
- [X] T021 [US2] Route `selection=files` + `condition=stale` +
  `--disposition reject|clarify` to `workflow_matching.decline_matching_threads`
  with `include_stale=True` (currently only fix+stale is wired via
  `_dispatch_stale_resolution`); add stale support to the decline dispatch path
  in `src/gh_address_cr/commands/agent.py` (`_dispatch_decline_resolution`,
  ~line 460). **Also remove the `if not parsed.match_files: raise
  MISSING_MATCH_FILES` gate in both `_dispatch_decline_resolution` (line ~462)
  and `_dispatch_stale_resolution` (line ~496)** — found by `/speckit-analyze`
  (F1): these two internal gates independently require `--match-files` even
  though C-A1/C-A5 commit to `--files`/`--file` alone being sufficient for
  selection=files (`--match-files` is deprecated per T028/data-model Entity 3,
  and neither function's file list actually depends on `parsed.match_files` —
  it is purely a confirmation gate). Without removing it, `--files
  --disposition reject` (no `--match-files`) — a valid C-A1 cell — would still
  fail with `MISSING_MATCH_FILES`. **And wire the decline reason from `--why`**
  (reason-flag unification, data-model Entity 1): change
  `_dispatch_decline_resolution` to pass the reason into
  `decline_matching_threads`'s `homogeneous_reason` parameter from
  `parsed.why` (falling back to the deprecated `parsed.homogeneous_reason`
  alias with a notice via T028), so `--why` is the decline reason for files
  selection exactly as it is for single (T012's `decline_item`). The
  `decline_matching_threads` signature/algorithm is unchanged — only which CLI
  flag feeds its existing param changes.
- [X] T022 [US2] Update the `agent resolve` argparse `--help`/epilog text in
  `src/gh_address_cr/commands/agent.py` (~lines 336–344) to describe the three
  axes (disposition, selection, condition) as the primary model, not a list of
  named modes.
- [X] T023 [US2] Run T017–T019 and confirm they pass; run
  `python3 -m unittest discover -s tests` for full-suite regression.

**Checkpoint**: The conflict matrix is gone — every valid combination works,
every invalid one gives one directive answer. Combined with US1, `agent
resolve` is now fully orthogonal.

---

## Phase 5: User Story 3 - Converge the surface without breaking existing callers (Priority: P3)

**Goal**: Shrink `agent resolve`'s mode-preset surface to ≤3 axis parameters,
keep every existing invocation working (with a visible deprecation notice)
through a versioned window, and align `submit-action` / `agent evidence add`
to the same disposition vocabulary (Option B, clarified 2026-07-08).

**Independent Test**: Run a representative set of today's mode-preset
invocations (`--stale --match-files`, `--reject --match-files
--homogeneous-reason`, `--include-stale`, `--trivial`, `--batch --input`)
against the new surface; each still resolves the same threads with the same
evidence and emits a visible deprecation notice.

### Tests for User Story 3

- [X] T024 [P] [US3] Test in `tests/test_agent_resolve_guards.py`: each
  deprecated flag combination from data-model.md Entity 3 — including the
  disposition booleans **`--trivial`/`--reject`/`--clarify`** (deprecated
  aliases for `--disposition trivial|reject|clarify`, R-4 correction),
  **`--batch`** (deprecated redundant confirmation of `--input`'s presence —
  found by `/speckit-analyze`: `--batch` without `--input` already errors
  `MISSING_BATCH_INPUT`, so it adds no behavior and belongs on the same
  deprecation list as `--match-files`), as well as `--match-files`, `--stale
  --match-files`, `--reject/--clarify --match-files --homogeneous-reason`,
  `--concern-label`, `--include-stale` — still produces the same resolution
  outcome as before **and** the stdout/stderr contains a deprecation notice
  naming the `--disposition`/axis equivalent (SC-005). **Also assert
  machine-output stability (FR-010, N3)**: for an equivalent legacy vs
  axis-form invocation of the same resolution, the machine-summary JSON
  fields/shape and the process exit code are unchanged (deprecation notice
  goes to stderr and does not alter the structured stdout summary), so the
  Status-to-Action contract stays byte-stable for existing consumers.
- [X] T025 [P] [US3] Test in `tests/test_disposition_vocabulary.py`, **widened**
  per the T003 consolidation: import the disposition set accepted by `agent
  resolve`'s CLI parser, `submit_action.parse_args`'s `--resolution` choices,
  `agent.roles.TERMINAL_RESOLUTIONS`, `core.agent_protocol_evidence.
  TERMINAL_RESOLUTIONS`, and `agent.responses.WORKFLOW_DECISIONS` — assert
  **all five** are the same canonical set, **modulo two stated exceptions**
  (found by `/speckit-analyze` I1, matching C-V2 exactly — do not assert a
  literal 5-way set equality without these): `trivial` (an `agent
  resolve`-only fix sub-mode, not a separate terminal value in the other four
  sites) and `defer` (present in `submit_action`'s choices and the three
  `TERMINAL_RESOLUTIONS`/`WORKFLOW_DECISIONS` sites, but **not** in `agent
  resolve`'s own `--disposition` enum, which is `{fix,trivial,reject,clarify}`
  only — data-model Entity 1). Compare `{fix, reject, clarify}` (the
  intersection all five genuinely share) plus assert `defer`'s presence/absence
  matches each site's documented support (C-V1, C-V2, SC-004a). This is the
  test that would have silently passed on only 3 of the 5 sites before the
  T003 consolidation — assert identity (`is`/aliasing where applicable) or
  value-equality against all of them, not just the two CLI-facing ones.
  **`agent evidence add` is explicitly NOT a 6th site** (`/speckit-analyze`
  E1): it has no disposition/resolution surface to import from, so this test
  does not — and should not attempt to — cover it; SC-004a documents this as
  excluded by construction.
- [X] T026 [P] [US3] Test that `submit-action`'s existing capabilities
  (file-based single-action submission) and `agent evidence add`'s existing
  capabilities (reusable evidence profiles, validation evidence, reply-evidence
  reconciliation) are unchanged after vocabulary alignment — run existing
  `tests/test_submit_action_helper.py` and evidence-add tests unmodified and
  confirm they still pass (C-V3, FR-006c — no capability regression).
- [X] T027 [P] [US3] Test that using a deprecated flag **after** a simulated
  removal window (feature-flag or version check in test) returns
  `RESOLVE_FLAG_DEPRECATED` and fails loudly rather than silently no-op-ing, in
  `tests/test_agent_resolve_guards.py`.

### Implementation for User Story 3

- [X] T028 [US3] Add a deprecation-alias layer in
  `src/gh_address_cr/commands/agent.py`: when a legacy flag is detected
  — **`--trivial`/`--reject`/`--clarify`** (mapped to `--disposition
  trivial|reject|clarify` — this is what T015's MVP normalization already
  does functionally; this task adds the **visible** notice on top), **`--batch`**
  (mapped to selection inferred from `--input` alone — `--batch` adds no
  behavior beyond `--input`'s presence, found by `/speckit-analyze`), or
  `--match-files`/`--include-stale`/`--homogeneous-reason`/`--concern-label`
  (mapped per data-model.md Entity 3) — emit a visible deprecation line to
  stderr naming the replacement, before continuing to dispatch normally.
- [X] T029 [US3] **Change** `submit_action.py`'s `--resolution` choices
  (`src/gh_address_cr/commands/submit_action.py` line ~25 — currently the
  hard-coded literal `choices=["fix", "clarify", "defer", "reject"]`,
  verified) to source its choice list from the shared
  `TERMINAL_RESOLUTIONS` constant (T003) used by `agent resolve` and
  `record_classification`, so there is no independent literal to drift (C-V2).
  Found by `/speckit-analyze` A1: this is an edit, not a verification —
  "Confirm" would have been read as a no-op.
- [X] T030 [US3] **Whole-`src/` guidance-string sweep** — migrate *every*
  runtime-emitted string that recommends a deprecated mode-preset flag or names
  a resolution disposition, to the axis phrasing. This is a **grep-driven
  class task, not a per-file list** (found by repeated `/speckit-analyze`
  passes each catching one more file — `cli.py`, `command_templates.py`,
  `workflow.py`, `workflow_matching.py`, `high_level.py`, `common.py`,
  `handle_agent_evidence`; the recurrence is the signal to sweep the class
  once). Behavior/parsing is unchanged; only emitted guidance text changes.
  Procedure:
  1. Run `grep -rn -- '--match-files\|--homogeneous-reason\|--include-stale\|--concern-label\|--stale --match-files\|resolve --trivial\|resolve --reject\|resolve --clarify\|resolve --batch' src/gh_address_cr/`
     — every hit that is **guidance/help/next-action/command-template text**
     (not the argparse flag *definitions* in `commands/agent.py`, and not the
     deprecation-alias machinery from T028, which legitimately name old flags)
     must be rewritten to the axis phrasing (`--files ... --disposition
     reject|clarify --why`, `--files ... --disposition fix --stale`, `--input`
     alone for batch, single-item `<item_id> --disposition reject --why`).
     Known sites to cover: `cli.py` help epilog (~L827–828);
     `core/command_templates.py` `resolve_homogeneous`/`resolve_decline`/
     `resolve_stale` (~L120–170, the machine-summary `commands` block agents
     consume — a public contract surface); `core/workflow.py` (~L203);
     `core/workflow_matching.py` (~L113/222/238); `commands/high_level.py`
     (~L282/484/485/964); `handle_agent_evidence` messages in
     `commands/agent.py` (~L635).
  1a. **Second grep pass for disposition-naming prose** (found by
      `/speckit-analyze` U3 — step 1's flag-pattern grep cannot match free text
      that names dispositions without a deprecated flag literal, so it silently
      never inspects these lines): run `grep -rn -- '--resolution <\|decide one
      resolution\|resolution: fix'
      src/gh_address_cr/` and manually review every hit for
      **completeness/accuracy** of the disposition list, not just deprecated
      phrasing. This surfaces (and fixes) a **real pre-existing bug**,
      independent of this feature, at `commands/high_level.py:964`: the
      guidance string reads `` --resolution <fix|clarify|defer> `` and **omits
      `reject`**, even though `submit_action.py`'s actual `--resolution`
      choices include it — exactly the disposition-vocabulary drift
      FR-006b/SC-004a exist to prevent, just in free text rather than a
      validated site. Fix to `` --resolution <fix|clarify|defer|reject> ``.
      `commands/high_level.py:282` ("fix, clarify, defer, or reject") is
      already complete — verified, no change needed there.
  2. Register `--disposition` in `commands/common.py`'s known-flags list
     (~L22, currently listing `--concern-label` etc.) so shell/arg tooling
     recognizes it.
  3. Re-run the grep after editing and assert zero remaining guidance-text
     hits (only argparse definitions + T028's alias machinery may remain).
  Ensure canonical disposition terms are used with no divergent synonyms
  (C-V1/C-V2). Note: `commands/high_level.py` is thus **in scope** — reconciles
  plan.md's Constitution Check (behavior untouched, guidance strings updated).
- [X] T031 [US3] Add the removal-window fail-loud path: after the documented
  deprecation window, legacy flag usage raises `RESOLVE_FLAG_DEPRECATED`
  instead of silently aliasing (implementation gated behind whatever
  version/flag mechanism T027's test expects — keep it simple, e.g. a single
  module-level constant marking the window as closed, defaulting to open).
- [X] T032 [US3] Reduce the `agent resolve` argparse `--help` presentation so
  the **primary** documented parameters are exactly the 2 axis-selecting
  flags — `--disposition {fix,trivial,reject,clarify}` and `--stale` (C-A9,
  research R-4) — well under the SC-004 cap of 3; all retired mode-preset
  flags (`--trivial`, `--reject`, `--clarify`, `--batch`, `--match-files`,
  `--homogeneous-reason`, `--concern-label`, `--include-stale`) remain
  functional (T028) but are documented as deprecated aliases in `--help`, not
  the primary surface.
- [X] T033 [US3] Run T024–T027 and confirm they pass; run
  `python3 -m unittest discover -s tests` for full regression across all three
  commands.

**Checkpoint**: All three user stories complete. `agent resolve` surface is
orthogonal and converged; existing callers are unaffected during the
deprecation window; `submit-action`/`agent evidence add` share one vocabulary.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, contract-map consistency, and final verification
across the whole feature.

- [X] T034 [P] Update `skill/references/status-action-map.md`: **(a) add** the
  new reason codes (`RESOLVE_AXIS_CONFLICT`, `RESOLVE_EVIDENCE_INCOHERENT`,
  `RESOLVE_FLAG_DEPRECATED`) under "Error States", with their directive
  next-action text (C-A7); **(b) revise** (not just add) **every** existing
  occurrence of a deprecated mode-preset flag in the file's action-guidance
  prose to the axis-based phrasing (`--files ... --disposition
  reject|clarify`, `--files ... --disposition fix --stale`, `--input` alone
  for batch). **Do not rely on a fixed line list** — line numbers have already
  drifted across prior `/speckit-analyze` passes on this file (known
  occurrences include `agent resolve --batch`, `agent resolve
  --homogeneous-reason <why>`, `agent resolve --stale --match-files`, and
  `agent resolve --batch --input <batch-response.json>`, at minimum). Run
  `grep -n -- '--batch\|--homogeneous-reason\|--match-files\|--include-stale\|--concern-label\|resolve --trivial\|resolve --reject\|resolve --clarify' skill/references/status-action-map.md`
  immediately before editing and again after, asserting zero remaining hits
  outside an explicit "deprecated aliases" section (if one is added). Found by
  `/speckit-analyze` (F1/I2): (a) alone would leave stale preset-flag guidance
  live in the same file as the new codes, and `tests/test_skill_docs.py`
  (T038) pins some of these exact strings, so both parts must land together.
- [X] T035 [P] Update `skill/references/agent-protocol.md` (lines ~40–48) to
  present the `agent resolve` command shapes as axis combinations (disposition
  / selection / condition) rather than a list of named modes, and document the
  deprecation mapping table from data-model.md Entity 3.
- [X] T036 [P] Update `skill/SKILL.md` (lines ~37–42, ~157) to replace the
  mode-preset example list and the "Use `agent resolve --homogeneous-reason`
  only for..." prose with the axis model description and the closed #204
  single-item-decline-including-stale example.
- [X] T037 [P] Update `README.md`'s deprecated-flag guidance — found by
  `/speckit-analyze` (F1): `README.md` isn't touched by any other Phase 6
  task despite containing multiple live occurrences naming the old mode
  presets as the documented path (known occurrences include
  `--homogeneous-reason`, `--stale --match-files`, and `--batch --input`, at
  minimum ~6 lines across the topology/examples sections). **Do not rely on a
  fixed line list**: run
  `grep -n -- '--batch\|--homogeneous-reason\|--match-files\|--include-stale\|--concern-label\|resolve --trivial\|resolve --reject\|resolve --clarify' README.md`
  before and after editing, asserting zero remaining hits (outside an explicit
  "deprecated" callout, if added). Replace with the axis-based phrasing
  (`--files ... --disposition reject|clarify`, `--files ... --disposition fix
  --stale`, `--input` alone for batch), consistent with T034–T036's treatment
  of `status-action-map.md`/`agent-protocol.md`/`SKILL.md`.
- [X] T038 [P] Update `tests/test_skill_docs.py` assertions that currently pin
  deprecated-preset literal strings (e.g. `"--stale --match-files"`,
  `"--homogeneous-reason"`, `"resolve --trivial"`, `"resolve --batch"`) as the
  canonical documented form, to assert the new axis-based phrasing instead,
  while still verifying the deprecation mapping is documented. **Do not rely
  on a fixed line list** — found by `/speckit-analyze` (I1): known occurrences
  span at least lines ~131, 182–183, 218–221, 603, 609–611, but this list has
  already proven incomplete across prior passes and will shift once
  T034–T037 land first. Run `grep -n -- '--batch\|--homogeneous-reason\|--match-files\|--include-stale\|--concern-label\|resolve --trivial\|resolve --reject\|resolve --clarify' tests/test_skill_docs.py`
  immediately before editing (after T034–T037) to enumerate every assertion
  that needs updating, and confirm the full suite (T040) is green afterward —
  a passing `python3 -m unittest tests.test_skill_docs` is the actual
  completion signal for this task, not a specific line count.
- [X] T039 Run `quickstart.md` Scenarios 1–6 manually (or via a driving test)
  against a local/fixture PR session and confirm each Success Signal.
- [X] T040 Run the full gate: `pip install -e .`, `ruff check src tests
  scripts/build_plugin_payload.py`, `python3 -m unittest discover -s tests`,
  `python3 -m gh_address_cr agent resolve --help`, `python3 -m gh_address_cr
  submit-action --help`, `python3 -m gh_address_cr agent manifest` — all green.
- [X] T041 Verify `agent resolve --help`'s **primary, axis-selecting** switch
  count is exactly 2 (`--disposition`, `--stale`) — under the SC-004 cap of
  3 — by diffing against the T002 baseline snapshot; confirm data-carrying
  selectors (`item_id`, `--files`, `--input`) and deprecated aliases are
  present but not counted as primary mode switches (C-A9).
- [X] T042 **N/A — automated, not hand-edited.** This repo uses
  `semantic-release` (`release.config.cjs` + `.github/workflows/release.yml`);
  `pyproject.toml` `version`, `src/gh_address_cr/__init__.py` `__version__`,
  and `CHANGELOG.md` are all bumped by CI from the conventional-commit type of
  the merge commit (`fix:`/`feat:`/`BREAKING CHANGE:` footer), not by hand.
  Manually editing them now would conflict with that automation. The
  versioned-contract-change intent (constitution Principle II) is satisfied by
  this PR's eventual conventional-commit message when merged to `main` — no
  file edits needed here.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories (the
  validator and vocabulary constant are shared).
- **User Story 1 (Phase 3, P1)**: Depends on Foundational. Independently
  testable and shippable as the MVP (closes #204).
- **User Story 2 (Phase 4, P2)**: Depends on Foundational; extends the
  validator and dispatch introduced/touched in US1. Should follow US1 (shares
  `_validate_resolve_axes` and the decline dispatch path) but does not require
  US1's tests to pass first if staffed separately — file-level overlap is in
  `commands/agent.py`, so sequential execution is recommended over parallel.
- **User Story 3 (Phase 5, P3)**: Depends on Foundational + benefits from US1/US2
  being complete (aliases map onto the final axis shape). Vocabulary-alignment
  tasks T025 (vocab test) and T029 (`submit_action` constant sourcing) are
  independent of US1/US2 and can start earlier if staffed separately. **T030
  (whole-`src/` guidance-string sweep) is NOT early-independent** — it must run
  after T015 (so new strings can name `--disposition`) and after T028 (so it
  can tell legitimate deprecation-alias mentions from guidance to migrate);
  schedule it late in US3.
- **Polish (Phase 6)**: Depends on US1–US3 complete.

### Within Each User Story

- Tests written first, confirmed failing, then implementation.
- `workflow.py` primitives before `commands/agent.py` dispatch wiring.
- Dispatch wiring before help-text/doc updates.

### Parallel Opportunities

- T002 (baseline snapshot) parallel with T001.
- T004, T006, T007 (Foundational) are parallel (different files).
- T008–T011 (US1 tests) are parallel (different assertions, though T008/T009/T011
  share the contract test file — coordinate file edits or write both in one
  pass).
- T017–T019 (US2 tests) parallel.
- T024–T027 (US3 tests) parallel.
- T034–T038 (Polish docs) parallel (different files).
- Because `commands/agent.py` is the shared hot file across US1/US2/US3
  implementation tasks, treat same-file implementation tasks (T012–T015,
  T020–T022, T028–T032) as **sequential**, not parallel, even where not marked.

---

## Parallel Example: User Story 1

```bash
# Tests (can be drafted in parallel, land in one commit):
Task: "Contract test single-item --disposition reject on fresh thread in tests/contract/test_resolve_axes_contract.py"
Task: "Contract test single-item --disposition clarify on stale thread in tests/contract/test_resolve_axes_contract.py"
Task: "Regression test in tests/test_agent_resolve_guards.py: item_id + stale/--disposition reject|clarify accepted"

# Implementation (sequential — same files):
Task: "Add workflow.decline_item(...) in src/gh_address_cr/core/workflow.py"
Task: "Add --disposition enum flag + wire _dispatch_single_item_resolution to decline_item in src/gh_address_cr/commands/agent.py"
Task: "Remove selected_modes/ITEM_ID_NOT_ALLOWED_FOR_MODE gates and call _validate_resolve_axes in src/gh_address_cr/commands/agent.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (axis vocabulary + validator skeleton + new
   reason codes).
3. Complete Phase 3: User Story 1 — closes issue #204.
4. **STOP and VALIDATE**: Run quickstart.md Scenarios 1–2 independently.
5. Ship/demo if ready — #204 is closed even before US2/US3 land.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. US1 → validate independently → #204 closed (MVP).
3. US2 → validate independently → conflict matrix eliminated.
4. US3 → validate independently → surface converged + compat window +
   3-command vocabulary alignment.
5. Polish → docs, status-action-map, version bump, full gate green.

### Parallel Team Strategy

With multiple contributors: one owns Foundational, then US3's early-independent
vocabulary tasks (T025 vocab test, T029 `submit_action` constant sourcing) can
proceed in parallel with US1; US2 should follow US1 sequentially due to shared
`commands/agent.py` dispatch/validator edits; **T030 (whole-`src/` string
sweep) runs last in US3**, after `--disposition` (T015) and the alias machinery
(T028) exist.

---

## Notes

- [P] tasks touch different files or independent assertions; same-file
  implementation tasks in `commands/agent.py` are intentionally left
  unmarked/sequential even within a story.
- This feature reuses existing kernel primitives throughout (R-1–R-3 in
  research.md) — no task introduces a new state-machine or lease algorithm.
- Public CLI/agent contract, Status-to-Action Map, and packaged-skill doc
  updates are mandatory per the constitution's Testable Contracts rule (T034–T038).
- Verify tests fail before implementing (US1–US3 test tasks precede their
  implementation tasks in each phase).
- Stop at each phase checkpoint to validate that story independently before
  proceeding.

---

## Phase 7: Convergence

**Purpose**: Close a gap surfaced by `/speckit-converge` that predates
implementation completion but was outside the original T001–T042 scope.

- [X] T043 Source `agent classify`'s `--classification` argparse choices in
  `src/gh_address_cr/commands/agent.py` (~line 165) from
  `agent.roles.TERMINAL_RESOLUTIONS` instead of the independent literal
  `["fix", "clarify", "defer", "reject"]` per FR-006b (partial). This is the
  same divergent-synonym-set pattern T003 consolidated for
  `core/agent_protocol_evidence.py` and `agent/responses.py`, in the same
  file T003/T015 heavily edited, but the `--classification` call site was
  missed. Widen `tests/test_disposition_vocabulary.py` with a regression
  assertion covering this site so it cannot silently re-diverge again. Run
  `python3 -m unittest discover -s tests` and `ruff check src tests
  scripts/build_plugin_payload.py` after the change.
