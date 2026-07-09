# Contract: Orthogonal Resolve Axes (CLI/Agent surface)

The observable public contract this feature commits to. Enforced by
`tests/contract/test_resolve_axes_contract.py` and updated
`tests/test_agent_resolve_guards.py`. This contract fixes the axes, their
legal combinations, **and** the concrete flag spelling for the
disposition/condition axes (R-4 correction: left open in an earlier draft,
but the surface syntax is load-bearing for SC-004 and is fixed here).

## C-A1 Three orthogonal axes, one flag each for disposition/condition

- Resolution is expressed as exactly one value on each of three axes:
  **disposition** ∈ {fix, trivial, reject, clarify}, **selection** ∈ {single,
  files, batch}, **condition** ∈ {fresh, stale}.
- **disposition** is surfaced as a single enum flag: `--disposition
  {fix,trivial,reject,clarify}` (default `fix`) — mirroring `submit-action`'s
  existing `--resolution` flag exactly. It is **not** surfaced as separate
  `--trivial`/`--reject`/`--clarify` booleans on the primary surface (those
  become deprecated aliases, C-A6).
- **condition** is surfaced as the single boolean `--stale`.
- **selection** is inferred from which pre-existing, data-carrying argument is
  present (`item_id` positional / `--files`/`--file` / `--input`) — no new
  selection-mode flag is introduced. `--batch` is **not** part of the primary
  surface: it is a redundant boolean confirmation of `--input`'s presence
  (`--batch` without `--input` errors `MISSING_BATCH_INPUT` regardless) and is
  a deprecated alias, exactly like `--match-files` is for `--files` (C-A6).
- Any value on one axis composes with any value on the others, **with one
  stated, intentional exception**: `disposition=trivial` is domain-restricted
  to `selection=single` (the existing `TRIVIAL_REQUIRES_ITEM_ID` check —
  found by `/speckit-analyze` F2 to be retained, un-deleted, and previously
  undocumented against this claim). `trivial` + `files`/`batch` selection
  fails with `TRIVIAL_REQUIRES_ITEM_ID`, not `RESOLVE_AXIS_CONFLICT` and not
  silent success — this is a genuine domain rule (a documentation/typo fast
  path only makes sense for one specific thread), not an artifact of the old
  mode-preset matrix. Every other cross-axis combination has **no** exclusion.
  (Enforced: the contract test asserts every cross-axis combination in the
  valid set is accepted, and this one stated exception is asserted
  explicitly, not silently skipped.)

## C-A2 Single-item decline — closes #204 (MVP, P1)

- `agent resolve <owner/repo> <pr> <item_id>` with disposition = `reject` or
  `clarify` and a reason MUST resolve that **one** thread: record classification,
  produce a published reply, reach terminal declined state, affect no other
  thread.
- This MUST hold whether the thread is **fresh or stale** (condition axis is
  independent — R-1).
- It MUST NOT return `ITEM_ID_NOT_ALLOWED_FOR_MODE` or
  `CONFLICTING_RESOLVE_MODE` for this valid intent.

## C-A3 Same-axis conflicts are the only exclusions (MVP, P2)

- Two selection sources at once (e.g. an `item_id` **and** a files selector) →
  `RESOLVE_AXIS_CONFLICT`, directive message naming the valid alternative.
- Two dispositions at once → `RESOLVE_AXIS_CONFLICT`.
- No other combination is rejected as a "mode conflict".

## C-A4 Disposition/evidence coherence (MVP, P2)

- The decline reason is **`--why`, for every selection** (single and files) —
  selection-independent, so the evidence axis does not depend on the selection
  axis (reason-flag unification, data-model Entity 1). `--homogeneous-reason`
  is a deprecated alias for `--why` (works with any selection during the
  window); `--summary` is fix-oriented and ignored by declines.
- Fix-only evidence (`--commit`/`--validation`) supplied with a decline
  disposition (`reject`/`clarify`) → `RESOLVE_EVIDENCE_INCOHERENT` (directive).
- A fix disposition missing its required evidence → the **existing** codes
  (`MISSING_RESOLVE_ARGS` for single, `MISSING_FIX_REPLY_COMMIT_HASH` for
  collective) — preserved, not renamed.
- A **decline** (single or files) with **no reason** (`--why` absent and no
  deprecated `--homogeneous-reason`) → `MISSING_RESOLVE_ARGS` with a
  decline-specific message (a decline must carry a reason; U1).

## C-A5 Selection values map to existing behavior (MVP)

- selection = `single` (item_id): routes to the single-item primitive path
  (fix/trivial via `workflow`, decline via classify+submit).
- selection = `files`: routes to `workflow_matching.*` (collective), preserving
  homogeneous decline and stale-fix behavior as **axis combinations** (files +
  reject/clarify; files + fix + stale). **`--files`/`--file` alone is
  sufficient** — the internal `MISSING_MATCH_FILES` gates in
  `_dispatch_decline_resolution` and `_dispatch_stale_resolution` that
  currently require `--match-files` too are removed (found by
  `/speckit-analyze` F1); `--match-files` becomes a no-op deprecated alias
  (C-A6), not a second requirement alongside `--files`.
- selection = `batch` (`--input`): unchanged batch behavior.

## C-A6 Deprecation aliasing + versioning (MVP, P3)

- Every retired mode flag (see data-model Entity 3) continues to work during the
  deprecation window, mapped to its axis equivalent, and emits a **visible**
  deprecation notice naming the replacement (never silent).
- Existing invocations produce the **same** resolution outcome and evidence as
  before (SC-005).
- After the removal window, a retired flag → `RESOLVE_FLAG_DEPRECATED`
  (fail-loud), never a silent no-op.
- The change is versioned as public CLI/agent behavior; machine summary fields,
  wait states, and exit codes are preserved or explicitly versioned.

## C-A7 Status-to-Action Map preserved + extended (MVP)

- All existing reason codes, statuses, wait states, and exit codes behave
  identically for equivalent intents.
- New codes (`RESOLVE_AXIS_CONFLICT`, `RESOLVE_EVIDENCE_INCOHERENT`,
  `RESOLVE_FLAG_DEPRECATED`) are **added** to `references/status-action-map.md`
  with their directive next-action.

## C-A8 Discoverability (MVP, P2)

- Command help presents the surface as three independent axes, not an
  enumeration of preset modes, so an agent can identify how to express any
  target intent without trial-and-error runtime rejection (SC-006).

## C-A9 Primary switch count (SC-004)

- After this change, `agent resolve --help`'s primary (non-deprecated) surface
  has exactly **2** axis-selecting switches — `--disposition` and `--stale`
  — well under the SC-004 cap of 3. Pre-existing data-carrying arguments
  (`item_id`, `--files`, `--input`, `--commit`, `--summary`, `--why`,
  `--validation`, etc.) are not counted (C-A1, research R-4).

## Verification

`python3 -m unittest discover -s tests` (new/updated:
`tests/contract/test_resolve_axes_contract.py`,
`tests/test_agent_resolve_guards.py`, `tests/test_disposition_vocabulary.py`,
`tests/test_skill_docs.py`) + `ruff check src tests` + CLI smoke
`python3 -m gh_address_cr agent resolve --help`. See [quickstart.md](../quickstart.md).
