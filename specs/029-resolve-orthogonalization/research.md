# Phase 0 Research: Resolve Command Orthogonalization

All Technical Context unknowns are resolved below. The central risk raised
during planning — whether "single-item × stale" resolution requires a
runtime-kernel change — was investigated (spec-clarify Option C) and resolved.

## R-1: Is "stale must be file-scoped" a safety invariant or an incidental façade limitation?

- **Decision**: **Incidental `agent resolve` façade limitation.** The kernel
  fully supports single-item resolution of stale threads for every disposition.
- **Rationale / evidence**:
  - `GITHUB_THREAD_CLAIMABLE_STATES = {open, blocked, waiting_for_fix, stale}` —
    stale is in the claimable set; `is_claimable_github_thread()` returns True
    for stale items (`core/github_thread_state.py`).
  - `tests/test_native_workflow.py::StaleThreadClaimabilityTests` proves stale
    threads are individually claimable by triage and (after classification) by
    fixer, and `test_stale_thread_classify_submit_publish_final_gate_path`
    exercises the full **single-item** `record_classification(item_id=…)` →
    `issue_action_request(role=fixer)` → single lease → `submit` (with
    fix evidence) → publish → final-gate path end-to-end.
  - `TERMINAL_RESOLUTIONS = {fix, clarify, defer, reject}`
    (`core/agent_protocol_evidence.py`) — the submit/apply path accepts every
    disposition for a single item.
  - Session evidence from this workstream: `agent classify <stale item_id>
    --classification reject` succeeded (`CLASSIFICATION_RECORDED`) on a stale
    thread — single-item stale decline is already supported at the protocol
    layer.
  - The stale exclusions are **path-local policy**, not a kernel invariant:
    `_is_batch_claimable_github_thread = claimable AND not stale` only keeps
    auto-generated `--batch` skeletons clean; `workflow_matching` excludes stale
    unless `include_stale`; `agent resolve` routes stale only to
    `--stale --match-files`. `--stale --match-files` itself was added for
    batch self-healing of a lease deadlock (issue #142), an additive
    convenience — not the only stale channel.
- **Alternatives considered**:
  - *Make stale individually claimable via a kernel change* — **rejected as
    unnecessary**: the kernel already supports it; no invariant needs changing.
  - *Narrow the spec so single-item × stale is out of scope* — **rejected**:
    based on a false premise; the capability exists, so SC-001/US1 stand.
- **Consequence**: Full orthogonality (spec Option B) needs **no kernel
  invariant change**; it is a dispatch-wiring + validator + docs refactor.

## R-2: Where does the #204 gap actually live?

- **Decision**: In `agent resolve`'s dispatch layer, not the kernel. The gap is
  that `_dispatch_single_item_resolution` (`commands/agent.py`) only wires
  `workflow.fast_fix_item` / `trivial_fix_item` (fix-only) and
  `_validate_resolve_mode` actively rejects `item_id` combined with
  `--reject/--clarify/--stale`. Decline/stale are only reachable through the
  collective `workflow_matching.*` path.
- **Rationale**: The single-item decline capability exists (`submit-action
  --resolution reject|clarify` → `apply_response_to_item`), but `agent resolve`
  never composed selection=single with disposition=decline.
- **Consequence**: The fix is to route `(selection=single × disposition=any ×
  condition=any)` to the granular classify+submit primitives, and
  `(selection=collective × …)` to `workflow_matching.*` — a unification of the
  current mode→function table into an axis→primitive router.

## R-3: What is the canonical disposition vocabulary across the three commands?

- **Decision**: One shared set: **`fix`, `trivial`, `reject`, `clarify`**
  (plus `defer` where a command already supports it, e.g. `submit-action`).
  `submit-action` already uses `--resolution {fix, clarify, defer, reject}`;
  `agent resolve` uses `fix`/`trivial` (single) and `reject`/`clarify` (decline).
  The union, deduplicated, is the canonical set.
- **Rationale**: `submit-action`'s `--resolution` is already value-based (not a
  preset flag), so it is the natural anchor for the vocabulary. Aligning
  `agent resolve`'s disposition names to it (and `evidence add` where it
  references dispositions) removes synonym drift (FR-006b).
- **Alternatives considered**: Inventing a new disposition vocabulary —
  rejected; it would break `submit-action`'s existing public contract for no
  gain. `trivial` is retained as a fix sub-mode (documentation/typo fast path)
  rather than a separate disposition, matching current semantics.
- **Correction (found by `/speckit-analyze`, verified against source)**: the
  original R-3 (and data-model.md Entity 2 / tasks.md T003) understated the
  problem — the canonical set `{fix, clarify, defer, reject}` is not backed by
  **one** existing constant today but by **three independently-defined,
  currently-coincidentally-equal** ones:
  `core/agent_protocol_evidence.py::TERMINAL_RESOLUTIONS` (used by
  `record_classification`), `agent/roles.py::TERMINAL_RESOLUTIONS` (used by
  `agent/responses.py::validate_action_response` to validate the
  `ActionResponse.resolution` field — i.e. the real runtime validator behind
  `agent submit`/`submit-action`), and `agent/responses.py::WORKFLOW_DECISIONS`
  (used by `validate_workflow_decision` to validate the separate
  `workflow_decision.v1` schema's `decision` field). A test that only compares
  `agent resolve`'s parser, `submit_action.parse_args`'s choices, and
  `core.agent_protocol_evidence.TERMINAL_RESOLUTIONS` (the original T025 scope)
  would pass while leaving `agent.roles`/`agent.responses`'s copies free to
  silently drift — exactly the failure mode FR-006b/SC-004a exist to prevent.
- **Revised decision**: consolidate to **one** true source —
  `agent/roles.py::TERMINAL_RESOLUTIONS` (the lowest-level module; already
  imported by `core/models.py`, `agent/responses.py`, `agent/requests.py`,
  `agent/manifests.py`, so it is the natural root). Change
  `core/agent_protocol_evidence.py::TERMINAL_RESOLUTIONS` and
  `agent/responses.py::WORKFLOW_DECISIONS` to import/alias it instead of
  independently defining an equal literal. T003 and T025 are amended
  accordingly (see tasks.md).

## R-4: How should the orthogonal axes surface on the CLI (composability without a matrix)?

- **Decision**: Three axis parameters, each a single independent choice:
  - **selection**: positional `item_id` (single) OR `--files/--file` scope OR
    `--input <batch>` (mutually exclusive *within the selection axis only* —
    a same-axis conflict, which is the only legitimate exclusion).
  - **disposition**: `--fix` (default) / `--trivial` / `--reject` / `--clarify`
    (one value; conflict only *within the disposition axis*).
  - **condition**: `--stale` as an independent boolean modifier usable with any
    selection and disposition (no longer implies `--match-files`).
- **Rationale**: Only *same-axis* conflicts remain (you cannot pick two
  selection sources or two dispositions at once) — those are inherent, not an
  emergent cross-axis matrix. Cross-axis combinations are all valid.
- **Correction (found by `/speckit-analyze`)**: "individual boolean flags vs a
  single enum are both acceptable" was **wrong** — it silently contradicts
  SC-004. Keeping `--trivial`/`--reject`/`--clarify` as three separate boolean
  switches (plus `--stale`) cannot hit "≤3 primary axis parameters" no matter
  how selection is spelled, since disposition alone would already consume 3–4
  switches. **Decision, now fixed**: disposition MUST be a **single enum flag**
  — `--disposition {fix, trivial, reject, clarify}` (default `fix`) — mirroring
  `submit-action`'s existing `--resolution {fix, clarify, defer, reject}`
  precedent exactly (same enum-flag *pattern*, R-3's vocabulary anchor extends
  naturally to the surface syntax too). `--trivial`/`--reject`/`--clarify`
  become **deprecated aliases** for `--disposition trivial|reject|clarify`,
  folded into the same deprecation-alias mechanism as the other retired flags
  (R-5), not kept as permanently-live parallel switches.
- **Resulting primary switch count**: `--disposition <value>` (1) +
  `--stale` (1) = **2** primary axis-selecting switches, under the SC-004
  cap of 3. Selection (`item_id` positional, `--files`, `--input`) is not
  counted as a "mode-preset switch" — these are pre-existing, data-carrying
  selectors (the same role `--files`/`--commit`/`--validation` already play),
  not boolean mode toggles; the ~9 being converged were specifically
  `{--batch, --trivial, --stale, --reject, --clarify, --homogeneous-reason,
  --concern-label, --match-files, --include-stale}`.
- **Note**: The contract (contracts/resolve-axes-cli.md) is updated to fix
  this concrete surface, not just the abstract axes.

## R-5: Backward compatibility / deprecation strategy

- **Decision**: **Deprecation window with visible aliases**, versioned as public
  behavior. Each retired mode flag maps to its axis equivalent, still works, and
  emits a visible deprecation notice naming the replacement. After the removal
  window, deprecated flags fail loudly with a pointer (never silent no-op).
- **Rationale**: Constitution Principle II ("CLI Is The Stable Public
  Interface" — machine-readable outputs, reason codes, wait states, exit
  codes, and stable input contracts MUST be preserved or versioned when
  changed; found by `/speckit-analyze` C1 — no section is literally titled
  "Compatibility Policy," Principle II is the actual anchor). Agents/scripts
  depending on `--stale --match-files`, `--reject --match-files`, etc. must
  not break on ship day.
- **Deprecation mapping** (authoritative list in data-model.md):
  `--match-files`→selection=files; `--homogeneous-reason`/`--concern-label`→
  files-selection decline reason; `--include-stale`→`--stale` modifier on a
  files selection; `--batch --input`→selection=batch; `--trivial`→disposition.
- **Alternatives considered**: Hard cutover — rejected (breaks callers,
  violates constitution Principle II). Silent aliasing — rejected (deprecation
  must be visible per FR-008).

## R-6: Contract-test strategy for "every cell reachable / invalid cells directive"

- **Decision**: An enumerated contract test (`tests/contract/
  test_resolve_axes_contract.py`) iterates the disposition × selection ×
  condition product, asserting each **valid** cell resolves through the expected
  primitive and each **invalid** intent (same-axis conflict; incoherent
  disposition/evidence pairing) returns exactly one directive reason code. A
  second test (`test_disposition_vocabulary.py`) asserts one canonical
  disposition set across the three commands.
- **Rationale**: Directly encodes SC-002/SC-003/SC-004a as executable contracts
  (testable-contracts rule); prevents regression back into an ad-hoc matrix.

## R-7: New reason-code placement — reuse `DEPRECATION_WINDOW_OPEN`?

- **Decision**: **No.** Define the three new codes (`RESOLVE_AXIS_CONFLICT`,
  `RESOLVE_EVIDENCE_INCOHERENT`, `RESOLVE_FLAG_DEPRECATED`) as new, centralized
  constants in `core/protocol_codes.py`, alongside the existing
  `FAST_FIX_REJECTED` / `MISSING_FIX_REPLY_COMMIT_HASH` precedent already
  imported by `commands/agent.py`.
- **Rationale**: `protocol_codes.py` already defines
  `DEPRECATION_WINDOW_OPEN = "DEPRECATION_WINDOW_OPEN"`, added in an unrelated
  feature (#179, "Implement deterministic rollout policy and state
  management" — a rollout/consolidation-slice policy, alongside
  `DUPLICATE_STATE_OWNER`, `INSUFFICIENT_EVIDENCE`, etc.), and it is **never
  consumed anywhere in the codebase** (verified by full-repo grep). Its name
  coincidentally matches this feature's "deprecation window" concept, but it
  belongs to a different subsystem's status vocabulary. Reusing an unrelated,
  orphaned constant just because the name matches would create a false
  cross-domain coupling (a resolve-command CLI status silently sharing
  identity with a rollout-policy status that could evolve independently) —
  which is the opposite of what centralization is for. `protocol_codes.py`'s
  own docstring states its purpose is "to prevent silent divergence from
  typo'd string literals" for the *same* concept, not to encourage reuse of an
  unrelated one.
- **Alternatives considered**:
  - *Reuse `DEPRECATION_WINDOW_OPEN` as the non-error status emitted while the
    window is open* — rejected per above.
  - *Define the three new codes inline in `commands/agent.py`* (the original
    plan) — rejected on closer inspection: the actual convention in this file
    is **mixed** (it already imports several centralized `protocol_codes.*`
    constants alongside inline literals), and the existing
    `MISSING_FIX_REPLY_COMMIT_HASH` precedent is a closer analog for a
    resolve-path-specific, reusable reason code than the ad hoc inline style.
  - *Also repurpose `DEPRECATION_WINDOW_OPEN` for T030's window-closed check* —
    rejected for the same false-coupling reason; T030 instead uses a new,
    feature-local flag/constant.

## Open items deferred to /speckit-tasks

- Exact final flag spelling per axis (enum vs boolean flags) — surface syntax.
- Deprecation window length (release count) — a release-policy decision, not a
  correctness item; the mechanism (visible alias + versioning) is fixed here.
