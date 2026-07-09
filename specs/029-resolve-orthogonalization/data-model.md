# Phase 1 Data Model: Resolve Command Orthogonalization

This feature introduces **no new persisted entities**. It re-expresses the
existing resolution surface as a product of orthogonal axes and defines the
deprecation mapping. The runtime session store, lease model, and evidence
records are unchanged.

## Entity 1: Resolution Intent (in-memory, not persisted)

A fully-specified resolution action = one value on each axis. Replaces the
former notion of a "resolve mode".

| Axis | Values | Notes |
|------|--------|-------|
| **disposition** | `fix` (default), `trivial`, `reject`, `clarify` (`defer` only where a command already supports it) | **Surfaced as a single enum flag** `--disposition {fix,trivial,reject,clarify}`, mirroring `submit-action`'s existing `--resolution` flag (R-4 correction — individual boolean flags per value cannot hit SC-004's ≤3 count). `trivial` is a fix sub-mode. |
| **selection** | `single` (by `item_id`), `files` (by `--files/--file` scope), `batch` (by `--input`) | Exactly one selection source per intent (same-axis exclusivity). Not counted toward SC-004 (pre-existing data-carrying selectors, not mode switches). |
| **condition** | `fresh` (default), `stale` | Independent modifier; composes with any selection + disposition. |
| **evidence** | fix → `commit` + `files` + `validation`; decline (`reject`/`clarify`) → `--why` (the **single** decline-reason flag for **all** selections — single *and* files, per the reason-flag unification below) | Determined by disposition, not by a separate mode. `--why` is selection-independent (orthogonal). `--summary` is fix-oriented and has no effect on a decline. `--homogeneous-reason` is a **deprecated alias for `--why`** (see reason-flag unification); `--concern-label` is a deprecated optional label. |
| **publish** | deferred (default) or immediate (`--publish`) | Unchanged. |

### Validation rules (axis-coherence validator — replaces the pairwise matrix)

- **Same-axis conflict** → directive error `RESOLVE_AXIS_CONFLICT` (new):
  two selection sources at once, or two dispositions at once.
- **Incoherent disposition/evidence** → directive error
  `RESOLVE_EVIDENCE_INCOHERENT` (new): fix-only evidence (`--commit`/
  `--validation`) supplied with a decline disposition, or decline reason without
  a disposition that consumes it.
- **Reason-flag unification** (deep-thinking correction — resolves a
  contradiction a prior round left: quickstart/T017 had used
  `--homogeneous-reason` as the files-scope decline reason while Entity 3
  simultaneously marked it deprecated). The decline reason is **`--why` for
  every selection** (single and files). Internally `decline_matching_threads`
  keeps its `homogeneous_reason` parameter, but `_dispatch_decline_resolution`
  feeds it from `--why` (T021). `--homogeneous-reason` is a **deprecated alias
  for `--why`** and works with any selection (emitting a deprecation notice,
  T028) — so `item_id + --homogeneous-reason` is simply a single decline whose
  reason came via the deprecated flag, **not** an axis conflict (dissolves
  `/speckit-analyze` U2 without a special rule). `--concern-label` stays a
  deprecated optional label.
- **Missing required evidence for the chosen cell** → existing reason codes are
  preserved and extended:
  - single fix missing `--commit/--summary/--why` → `MISSING_RESOLVE_ARGS`;
  - collective fix missing `--commit` → `MISSING_FIX_REPLY_COMMIT_HASH`;
  - **decline (single or files) with no reason at all** — neither `--why` nor
    the deprecated `--homogeneous-reason` — → `MISSING_RESOLVE_ARGS` with a
    decline-specific message (resolves `/speckit-analyze` U1; `decline_item`
    (T012) and the files decline path both require a reason, consistent with
    Principle III "a decline needs a reason"). Tested in T010/T011/T017.
- **One stated, intentional cross-axis exclusion** (found by `/speckit-analyze`
  F2, previously undocumented against the "no cross-axis exclusion" claim):
  `disposition=trivial` requires `selection=single` — the existing, retained
  `TRIVIAL_REQUIRES_ITEM_ID` check (`commands/agent.py` lines ~437–444, not
  touched by T014's gate removal). `trivial` + `files`/`batch` →
  `TRIVIAL_REQUIRES_ITEM_ID`, a genuine domain rule (a doc/typo fast path only
  makes sense for one thread), not leftover matrix debris.
- **`--files`/`--file` alone is sufficient for selection=files** (found by
  `/speckit-analyze` F1): the internal `MISSING_MATCH_FILES` gates in
  `_dispatch_decline_resolution` and `_dispatch_stale_resolution` — which
  independently required `--match-files` even though it is now a deprecated,
  behavior-inert alias — are removed. Without this, `files + reject/clarify`
  or `files + fix + stale` without `--match-files` would still (incorrectly)
  fail, even though they are valid cells.
- **All other valid cross-axis combinations MUST NOT error** (SC-003). The
  retired codes `ITEM_ID_NOT_ALLOWED_FOR_MODE` and `CONFLICTING_RESOLVE_MODE`
  (when triggered by *valid* intents) are removed from the valid-path logic.

### Routing (axis intent → existing primitive; no new algorithm)

| selection | disposition | condition | Routes to (existing primitive) |
|-----------|-------------|-----------|-------------------------------|
| single | fix / trivial | fresh or stale | `workflow.fast_fix_item` / `trivial_fix_item` (item is claimable incl. stale — R-1) |
| single | reject / clarify | fresh or stale | `record_classification(item_id, …)` → `issue_action_request` → `submit_action_response` / `apply_response_to_item` (the NEW single-item decline wiring, onto existing primitives) |
| files | fix | fresh (or stale via condition) | `workflow_matching.fast_fix_matching_threads` |
| files | reject / clarify | fresh (or stale via condition) | `workflow_matching.decline_matching_threads` (via `--files` alone, `MISSING_MATCH_FILES` gate removed — F1) |
| files | fix | stale | `workflow_matching.fast_fix_matching_threads(stale_only=True)` (via `--files` alone — F1) |
| batch | per-thread | mixed | `workflow_matching` batch path (`--input`) |
| **files or batch** | **trivial** | — | **Invalid** — `TRIVIAL_REQUIRES_ITEM_ID` (F2); not a routable cell, listed here so it is not silently omitted. |

## Entity 2: Disposition Vocabulary (canonical constant)

- One shared terminal-resolution enumeration used identically by `agent
  resolve`, `submit-action`, and `agent evidence add`: `{fix, clarify, defer,
  reject}`.
- **Pre-existing triplication (found by `/speckit-analyze`, R-3 correction)**:
  before this feature, this set was independently defined in **three**
  places with no shared source: `core/agent_protocol_evidence.py::
  TERMINAL_RESOLUTIONS` (feeds `record_classification`), `agent/roles.py::
  TERMINAL_RESOLUTIONS` (feeds `agent/responses.py::validate_action_response`
  — the real validator behind `agent submit`/`submit-action`), and
  `agent/responses.py::WORKFLOW_DECISIONS` (feeds `validate_workflow_decision`
  for the separate `workflow_decision.v1` schema). They happened to hold the
  same literal value, but nothing enforced that. This feature's canonical
  constant work (T003) now **consolidates** these onto one true source:
  `agent/roles.py::TERMINAL_RESOLUTIONS` (the lowest-level module; already the
  common import root for `core/models.py`, `agent/responses.py`,
  `agent/requests.py`, `agent/manifests.py`). The other two sites import/alias
  it instead of independently defining an equal literal. No command may define
  a divergent synonym set for this shared set (FR-006b, SC-004a).
- `trivial` is **excluded** from this cross-command set: it is an `agent
  resolve`-only disposition-axis sub-value that selects the
  documentation/typo fast path *within* the `fix` terminal resolution. It is
  not expected on `submit-action`, and the cross-command equality assertion in
  `tests/test_disposition_vocabulary.py` (T025, widened) checks the four
  terminal resolutions across `agent resolve`'s disposition axis,
  `submit_action.parse_args`'s `--resolution` choices,
  `agent.roles.TERMINAL_RESOLUTIONS`,
  `core.agent_protocol_evidence.TERMINAL_RESOLUTIONS`, and
  `agent.responses.WORKFLOW_DECISIONS` — **5 sites** (corrected,
  `/speckit-analyze` I1: `core.agent_protocol_evidence.TERMINAL_RESOLUTIONS`
  remains an independently-importable site even as a T003 alias, and T025
  checks it explicitly — an earlier draft omitted it here, undercounting to
  4), modulo `trivial`/`defer` per FR-006b.
- `agent evidence add` is **not** one of the 5 sites and is **not** checked by
  T025 — it has no disposition/resolution surface (`handle_agent_evidence` and
  the evidence functions it calls reference no resolution value at all).
  Excluded by construction (correction, `/speckit-analyze` E1: a prior draft
  claimed this was "transitive" coverage, which had no code to back it).

## Entity 3: Deprecation Mapping (versioned, for the compatibility window)

Each retired mode-preset flag maps to its orthogonal-axis equivalent; the old
flag still works during the window, emits a visible deprecation notice, and is
removed (fail-loud) after the window.

| Deprecated flag | Orthogonal equivalent | Notes |
|-----------------|-----------------------|-------|
| `--match-files` | selection = `files` (`--files/--file`) | No longer a separate mode gate; it *is* the files selection. |
| `--stale --match-files` | selection = `files` + condition = `--stale` | `--stale` becomes an independent modifier. |
| `--reject/--clarify --match-files --homogeneous-reason` | selection = `files` + `--disposition reject\|clarify` + `--why` | Homogeneous decline is a files-scope decline; the reason moves to `--why` (row below). |
| `--homogeneous-reason` | `--why` (decline reason, any selection) | Deprecated **alias for `--why`** (reason-flag unification): its mode-selecting role → axes, its reason-value role → `--why`. Works with single or files selection during the window. |
| `--concern-label` | optional label on a files-scope decline, still functional | **Correction (found by `/speckit-analyze` I2)**: this row previously said "retained, not a mode," contradicting spec.md's own opening enumeration of the ~9 mode-preset switches being converged (which includes `--concern-label`) and tasks.md T024/T028/T032's consistent treatment of it as deprecated. `--concern-label` **is** deprecated, on the same lifecycle as the `--homogeneous-reason` shortcut it labels (it has no meaning independent of that shortcut) — it keeps working during the compat window with a deprecation notice, not permanently. |
| `--include-stale` | condition = `--stale` on a files selection | Folded into the condition axis. |
| `--trivial` | `--disposition trivial` | **R-4 correction**: `--trivial` is deprecated in favor of the enum flag, not kept as a permanent parallel boolean — same rule applies to `--reject`/`--clarify` below. |
| `--reject` | `--disposition reject` | Deprecated boolean → enum value (R-4 correction; required for SC-004's ≤3 count). |
| `--clarify` | `--disposition clarify` | Deprecated boolean → enum value (R-4 correction). |
| `--batch` | selection inferred from `--input` alone | **Found by `/speckit-analyze`**: `--batch` is deprecated too, mirroring `--match-files`. Verified in `commands/agent.py`: `_dispatch_agent_resolve` triggers the batch path on `parsed.batch or parsed.input`, and `--batch` **without** `--input` immediately errors `MISSING_BATCH_INPUT` requiring `--input` anyway — `--batch` adds no behavior beyond `--input`'s mere presence, so it does not belong on the primary (non-deprecated) surface either. `--input <path>` alone is necessary and sufficient for selection = `batch`. |
| `<item_id> --reject/--clarify` **(previously rejected)** | **now valid** | The #204 fix — no longer an error. |
| `<item_id> --stale` **(previously rejected)** | **now valid** | Single stale by id — now valid (R-1). |

## Reason codes (Status-to-Action Map additions)

New (added, not repurposed; defined as centralized constants in
`core/protocol_codes.py` — not reused from the unrelated, orphaned
`DEPRECATION_WINDOW_OPEN` constant, see research.md R-7; must be documented in
the map):

- `RESOLVE_AXIS_CONFLICT` — two values on the same axis (directive; names the
  valid alternative).
- `RESOLVE_EVIDENCE_INCOHERENT` — disposition/evidence mismatch (directive).
- `RESOLVE_FLAG_DEPRECATED` — a retired flag was used after the removal window
  (fail-loud, points to the axis equivalent). During the window a non-error
  deprecation notice is emitted instead.

Preserved unchanged: `MISSING_RESOLVE_ARGS`, `MISSING_FIX_REPLY_COMMIT_HASH`,
`FAST_FIX_ACCEPTED`, `STALE_RESOLUTION_ACCEPTED`, `DECLINE_ALL_*`,
`ACTION_ACCEPTED`, and all publish/final-gate codes.

Retired from the *valid* path (only fire for genuine same-axis misuse, or
removed): `ITEM_ID_NOT_ALLOWED_FOR_MODE`, `CONFLICTING_RESOLVE_MODE`.
