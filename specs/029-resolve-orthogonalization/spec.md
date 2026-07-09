# Feature Specification: Resolve Command Orthogonalization

**Feature Branch**: `029-resolve-orthogonalization`
**Created**: 2026-07-08
**Status**: Draft
**Input**: User description: "消除矩阵(正交化)，并收敛必要的指令，按照上下文来看，修复204，和存在的历史问题。"

## Summary

The `agent resolve` command has accreted ~22 flags, of which ~9 are mutually
constraining "mode" switches (`--batch`, `--trivial`, `--stale`, `--reject`,
`--clarify`, `--homogeneous-reason`, `--concern-label`, `--match-files`,
`--include-stale`). Each mode flag is a bundled preset that pins several
independent decisions at once, so the flags overlap, conflict pairwise, and
still fail to cover every needed combination. The concrete gap (issue #204) is
that an agent cannot decline (**reject**/**clarify**) **one specified** review
thread by `item_id` — and cannot decline a **stale** thread at all — even
though the underlying protocol supports it. This feature replaces the flat
mode-preset enumeration with a small set of **orthogonal, independently
composable axes**, so every valid disposition × selection × condition
combination is reachable, the emergent conflict matrix disappears, and the
public command surface converges to fewer, clearer parameters — while the
underlying resolution protocol and its evidence/gating guarantees stay intact.
This v1 applies the same orthogonal axis model across the **whole user-facing
resolution/evidence surface** — `agent resolve`, `agent evidence add`, and
`submit-action` — so disposition, selection, and evidence vocabulary is uniform
across all three commands, not just internally consistent within `agent
resolve`.

## Clarifications

### Session 2026-07-08

- Q: Should v1 include `agent evidence add` and `submit-action` in the
  orthogonalization, or only `agent resolve`? → A: Include all three. v1 unifies
  the resolution/evidence surface (`agent resolve`, `agent evidence add`,
  `submit-action`) under one orthogonal axis model in a single pass; `agent
  resolve` gets its emergent conflict matrix removed, while `submit-action` and
  `evidence add` are aligned to the same disposition/selection/evidence
  vocabulary (they lack the pairwise-conflict matrix, so their change is
  vocabulary/consistency alignment rather than matrix removal).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Decline one specific review thread, including when it is stale (Priority: P1)

An agent triaging a PR decides a single, specific review comment should be
declined rather than fixed (a **reject** with reasoning, or a **clarify**
request). It must be able to do this for exactly that one thread, addressed by
its `item_id`, regardless of whether the thread is fresh or `STALE`/outdated —
with a reason recorded and a reply published — in one uniform command shape.

**Why this priority**: This is the exact capability gap reported in issue #204.
It blocks the "decline a single thread" and "decline a stale thread" cases with
no ergonomic path today, forcing agents into trial-and-error or the low-level
protocol. It is the smallest slice that delivers user value and closes the
reported defect.

**Independent Test**: Take a PR with one open thread and one stale thread.
Decline each individually by `item_id` with a reason; confirm a reply is
recorded and the thread reaches its terminal declined state, with no
"mode not allowed" / "conflicting mode" rejection.

**Acceptance Scenarios**:

1. **Given** an open review thread identified by `item_id`, **When** the agent
   declines it as **reject** with a reason, **Then** the runtime records the
   classification and reply evidence for that single thread and it becomes
   terminally handled, with no other thread affected.
2. **Given** a `STALE`/outdated review thread identified by `item_id`, **When**
   the agent declines it as **clarify** with a reason, **Then** the stale
   thread is handled for that single item without requiring a file-scoped
   collective selector.
3. **Given** a request to decline a single thread, **When** it is submitted,
   **Then** the runtime never returns a mutually-exclusive-mode error
   (`ITEM_ID_NOT_ALLOWED_FOR_MODE`, `CONFLICTING_RESOLVE_MODE`) for the valid
   combination.

### User Story 2 - Compose any disposition with any selection and condition (Priority: P2)

An agent expresses a resolution as an independent choice on each axis —
**what** to do (fix / trivial / reject / clarify), **which** threads
(one by id / many by file scope / an explicit batch), and the **thread
condition** it is targeting (fresh / stale) — and any valid combination is
accepted. Invalid combinations produce a single directive error that names the
valid alternative, rather than an emergent matrix of pairwise exclusions.

**Why this priority**: Removing the conflict matrix is what makes the surface
predictable and prevents the accretion from recurring. It generalizes US1 so
future dispositions/selections compose for free instead of each needing a new
preset flag.

**Independent Test**: Enumerate the disposition × selection × condition
combinations; confirm each valid cell is reachable with a uniform command shape
and each invalid cell fails with one directive, self-explaining error.

**Acceptance Scenarios**:

1. **Given** any disposition, **When** it is combined with a single-item
   selection, **Then** the command is accepted (no disposition is
   selection-locked).
2. **Given** a disposition combined with the stale condition, **When**
   submitted with a valid selection, **Then** it is accepted (condition is an
   independent axis, not fused into specific dispositions).
3. **Given** two conflicting values on the **same** axis (for example two
   selection sources at once), **When** submitted, **Then** the command fails
   loudly with one directive error that states the valid alternative.

### User Story 3 - Converge the surface without breaking existing callers (Priority: P3)

Maintainers and existing agent scripts benefit from a smaller, orthogonal
parameter set. Existing invocations that use today's mode-preset flags continue
to work through a documented, versioned deprecation window mapped onto the new
axes, with deprecation surfaced (not silent), so no caller breaks on the day
the new surface ships.

**Why this priority**: Convergence is the durable win, but it must not regress
the public CLI/agent contract. Backward compatibility and versioning are a
constitutional requirement, so this slice makes the migration safe and
observable rather than a hard cutover.

**Independent Test**: Run a representative set of today's mode-preset
invocations against the new surface; confirm each still resolves the same
threads with the same evidence and emits a visible deprecation signal pointing
to the orthogonal equivalent.

**Acceptance Scenarios**:

1. **Given** an existing mode-preset invocation, **When** run after this change,
   **Then** it produces the same resolution outcome and evidence as before, plus
   a visible deprecation notice naming the orthogonal replacement.
2. **Given** the converged surface, **When** an agent reads the command help,
   **Then** the parameters are presented as independent axes (not a matrix of
   preset modes), and the count of mode-preset switches is reduced.

### Edge Cases

- Declining a **single stale** thread by `item_id` (the combination with no
  path today) MUST be reachable.
- An explicit **batch** of per-thread decisions MUST remain expressible on the
  new surface (batch is a selection value, not a lost capability).
- Declining the **same repeated concern across many threads** with one shared
  reason MUST remain expressible (it becomes selection = file/concern scope +
  disposition = reject/clarify, not a dedicated preset).
- A resolution that supplies **fix evidence** (commit/files/validation) together
  with a **decline** disposition (which needs only a reason) MUST fail loudly as
  an incoherent request, with a directive message.
- A request naming **two selection sources at once** (e.g. an `item_id` and a
  file-scope selector) MUST fail loudly rather than silently pick one.
- Deprecated mode-preset flags used **after** the removal window MUST fail
  loudly with a pointer to the orthogonal equivalent, never silently no-op.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The resolution surface MUST expose resolution as independent
  axes — at minimum **disposition** (fix, trivial, reject, clarify),
  **selection** (single thread by id, file/concern scope, explicit batch), and
  **thread condition** (fresh, stale/outdated) — where any value on one axis
  composes with any value on the others for all combinations the domain allows.
- **FR-002**: An agent MUST be able to apply **reject** or **clarify** to a
  **single** thread addressed by `item_id`, recording a reason and producing a
  published reply, closing issue #204.
- **FR-003**: The **stale/outdated** condition MUST be an independent selectable
  condition usable with single-item selection and with **every** disposition
  (fix, trivial, reject, clarify — this list is exhaustive, not illustrative;
  found by `/speckit-analyze` U1, a prior draft omitted `trivial` here even
  though data-model.md's routing table always included it), not fused only
  into a fix-by-file-scope preset.
- **FR-004**: For every **valid** axis combination, the runtime MUST NOT emit a
  mutually-exclusive-mode rejection. The emergent pairwise conflict matrix
  (e.g. `ITEM_ID_NOT_ALLOWED_FOR_MODE`, `CONFLICTING_RESOLVE_MODE` for valid
  intents) MUST be eliminated.
- **FR-005**: For **invalid** requests (conflicting values on the same axis, or
  incoherent axis pairings such as fix-evidence with a decline disposition), the
  runtime MUST fail loudly with a single directive error that names the valid
  alternative — never silently pick a mode.
- **FR-006**: The public command surface MUST converge: the number of
  mode-preset switches on `agent resolve` MUST be reduced, replaced by the
  orthogonal axis parameters, with the former presets either retired or
  expressible as combinations of the axes.
- **FR-006a**: The orthogonal axis model MUST be applied across the v1
  resolution/evidence surface — `agent resolve`, `agent evidence add`, and
  `submit-action` — to the extent each command exposes the relevant axis.
  `agent evidence add` (`handle_agent_evidence` and the evidence functions it
  calls) has **no disposition/resolution surface at all** — it records
  reply/validation/profile evidence only — so it is **excluded by
  construction** from the disposition-vocabulary alignment, not covered
  through some indirect reliance (correction found by `/speckit-analyze` E1,
  replacing a prior draft's incorrect "transitive" claim). Its selection
  concept (`--item-id`/`--thread-id`/`--files`) already matches the same
  shape as `agent resolve`'s selection axis, which is the extent of its
  alignment. Where the axes *are* surfaced, disposition, selection, and
  evidence are expressed the same way. "Expressed the same way" means the
  **accepted
  value set** is identical (FR-006b) and sourced from one shared constant —
  it does **not** require identical flag *names*: `agent resolve` keeps
  `--disposition` and `submit-action` keeps its existing `--resolution`, each
  per that command's own established convention (found by `/speckit-analyze`
  A1, matching contracts/disposition-vocabulary.md C-V4). `submit-action` and
  `agent evidence add` do not carry `agent resolve`'s pairwise-conflict
  matrix; for them this is vocabulary/consistency alignment, not matrix
  removal.
- **FR-006b**: A single canonical **terminal-resolution** vocabulary —
  **fix / clarify / defer / reject** — MUST be sourced from one shared
  constant wherever a command exposes or validates resolution values, with no
  command defining a divergent synonym set. **Two documented carve-outs** (a
  command need not expose the *whole* set, only draw from the shared source
  without divergence):
  - `trivial` is **not** part of the shared set: it is an `agent resolve`-only
    disposition-axis sub-value selecting the documentation/typo fast path
    **within** the `fix` terminal resolution; not on `submit-action`/`agent
    evidence add`.
  - `defer` is accepted by `submit-action`'s `--resolution` (and lives in the
    shared constant) but is **not** offered on `agent resolve`'s
    `--disposition` enum, which is `{fix, trivial, reject, clarify}` — declining
    to fix vs deferring are the review-thread dispositions `agent resolve`
    surfaces; `submit-action` retains `defer` for its loop-action contract.
    (Found by `/speckit-analyze` I1: an earlier draft asserted strict
    same-set-same-names identity, contradicting `agent resolve`'s deliberate
    omission of `defer`.)
- **FR-006c**: Aligning the sibling commands MUST NOT drop any current
  capability: `submit-action`'s file-based single-action submission and
  `agent evidence add`'s reusable evidence recording and reply-evidence
  reconciliation MUST remain expressible after the change.
- **FR-007**: Existing invocations using today's mode-preset flags MUST continue
  to produce equivalent resolution outcomes and evidence during a documented
  deprecation window, mapped onto the orthogonal axes, with the compatibility
  surface **versioned** as public behavior.
- **FR-008**: Deprecated usage MUST surface a **visible** deprecation signal
  (not silent) that names the orthogonal replacement; after the removal window,
  deprecated flags MUST fail loudly rather than silently no-op.
- **FR-009**: The change MUST preserve the underlying resolution protocol and
  its guarantees: classification recording, lease ownership, required evidence,
  reply-and-resolve dual requirement for GitHub threads, publish path, and
  final-gate authority MUST behave identically for equivalent intents.
- **FR-010**: Machine-readable outputs (status, reason codes, wait states, exit
  codes, structured action requests/responses) MUST remain stable or be
  explicitly versioned; the **Status-to-Action Map** MUST be preserved. Any new
  reason code for an invalid axis combination MUST be documented in the map.
- **FR-011**: Command help/discovery MUST present the resolution surface as
  independent axes rather than an enumeration of preset modes, so valid
  combinations are discoverable up front instead of via trial-and-error runtime
  rejections.
- **FR-012**: The packaged skill guidance (SKILL.md and agent-protocol
  references) MUST be updated to describe the orthogonal axes and the single
  uniform command shape, and MUST stop presenting the mode-preset matrix as the
  primary path.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: Affects GitHub review-thread resolution intake and
  the reply/resolve side effects. The deterministic owner (the runtime
  resolution protocol: classify → claim → submit → publish) is unchanged; this
  feature only changes the **surface** that drives it. Session state, findings
  intake, loop safety, audit artifacts, and final-gate authority are unchanged.
- **Runtime Kernel Model**: External facts/event inputs (review threads, their
  fresh/stale condition, lease state) are unchanged. The projection is the same
  item state machine. The policy/decision surface gains a directive validation
  for axis coherence (replacing emergent pairwise exclusions). The
  side-effect/outbox boundary (published replies, resolved threads) and artifact
  truth boundary are unchanged. Replay/contract tests MUST cover each axis cell
  and each invalid-combo directive error.
- **CLI / Agent Contract Impact**: This is a **public CLI/agent contract
  change** across the resolution/evidence surface — `agent resolve`,
  `agent evidence add`, and `submit-action` (three public commands). It MUST be
  versioned; existing machine summary fields, reason codes, wait states, and
  exit codes MUST be preserved or explicitly versioned; the **Status-to-Action
  Map** MUST be preserved. New invalid-combination reason codes MUST be added to
  the map. `submit-action`'s structured action-request/response format is
  preserved; only its resolution/disposition vocabulary is aligned. The broader
  three-command surface increases the versioning/deprecation blast radius, which
  MUST be handled with the same deprecation-window + alias discipline as
  `agent resolve`.
- **Evidence Requirements**: Unchanged per intent. A fix still requires
  commit/files/validation; a decline still requires a reason; a GitHub thread is
  terminal only with a concrete reply URL from the authenticated login. The
  orthogonal surface MUST map to exactly the same evidence obligations as the
  equivalent preset does today.
- **Packaged Skill Boundary**: Runtime behavior/validation belongs in the
  runtime package (repo-root development). The **thin adapter** SKILL.md and
  `references/agent-protocol.md` updates belong under `skill/`. The Thin Adapter
  and Behavioral Policy Layer model is preserved — the skill continues to
  describe, not reimplement, the resolution protocol.
- **External Intake Replaceability**: Unchanged. The Normalized Findings
  Contract and intake-agnostic control plane are not touched; this feature is
  about the resolution/decline surface, not findings ingestion.
- **Telemetry Evidence Boundary**: No new telemetry semantics required.
  Existing per-invocation span behavior is unchanged; telemetry remains observed
  evidence, not review-resolution state.
- **Architecture Plateau Risk**: This feature **reduces** state space and
  ambiguity — it removes an emergent conflict matrix and collapses ~9 overlapping
  preset flags into a few orthogonal axes. It does not add unmodeled state flags,
  fallbacks, or artifact-backed truth; it removes them. This is a convergence,
  not an accretion, and is therefore the correct response to the plateau signal
  identified in issue #204.
- **Fail-Fast Behavior**: Conflicting values on one axis, incoherent
  disposition/evidence pairings, unknown `item_id`, and post-removal use of
  retired flags MUST fail loudly with directive messages. Valid combinations
  MUST NOT fail.

### Key Entities *(include if feature involves data)*

- **Resolution Intent**: A point in the axis product space —
  (disposition, selection, condition, evidence, publish-timing) — that fully
  describes one resolution action. Replaces the notion of a "mode".
- **Disposition**: What the agent decides for the selected thread(s): fix,
  trivial, reject, clarify (and defer where applicable).
- **Selection**: Which thread(s) the intent targets: one by `item_id`, a
  file/concern scope, or an explicit batch of per-thread decisions. Applies
  uniformly across `agent resolve`, `agent evidence add`, and `submit-action`.
- **Thread Condition**: The state of the targeted thread(s): fresh or
  stale/outdated — an independent axis, not bound to a disposition.
- **Deprecation Mapping**: The versioned correspondence from each retired
  mode-preset flag to its orthogonal-axis equivalent, used for backward
  compatibility and deprecation messaging.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An agent can decline (reject or clarify) a single specified thread
  by `item_id`, including a stale thread, in **one command** with no
  mutually-exclusive-mode rejection — issue #204 is closed and verified by an
  automated test.
- **SC-002**: **100%** of valid disposition × selection × condition combinations
  are reachable through the orthogonal surface, verified by an enumerated
  contract test covering every cell.
- **SC-003**: **Zero** mutually-exclusive-mode errors are emitted for valid
  intents; every invalid intent instead yields a single directive error naming
  the valid alternative.
- **SC-004**: The number of **primary, non-deprecated, axis-selecting**
  switches on `agent resolve` is reduced from ~9 to no more than **3**
  (concretely: one `--disposition <value>` enum flag and one `--stale`
  condition flag — 2 — per research.md R-4). Measured immediately after this
  feature ships, against the parameters `--help` presents as the primary
  documented surface (per FR-011). Counted switches are boolean/enum
  **mode-selecting** flags only — the original ~9 being converged were
  `{--batch, --trivial, --stale, --reject, --clarify, --homogeneous-reason,
  --concern-label, --match-files, --include-stale}`. Pre-existing,
  data-carrying selectors (`item_id` positional, `--files`, `--input`, and
  evidence flags like `--commit`/`--validation`) are **not** counted — they
  identify *what* to act on or *what evidence* to record, not *which mode*,
  and were never part of the ~9. Retired mode-preset flags kept alive as
  deprecation aliases during the FR-007/FR-008 compatibility window (see
  data-model.md Entity 3) are also excluded from this count — documented as
  deprecated, not part of the primary surface — and their eventual removal is
  a compatibility-window milestone, not a precondition for meeting SC-004.
- **SC-004a**: The **terminal-resolution** vocabulary (fix / clarify / defer /
  reject) is **drawn from one shared constant** wherever a command actually
  exposes or validates a resolution/disposition value, with no divergent
  synonyms — verified by a contract test over the sites that reference it:
  `agent resolve`'s `--disposition` choices, `submit-action`'s `--resolution`
  choices, and the shared constants behind them
  (`agent.roles.TERMINAL_RESOLUTIONS`,
  `core.agent_protocol_evidence.TERMINAL_RESOLUTIONS`,
  `agent.responses.WORKFLOW_DECISIONS`) — **5 sites total** (found by
  `/speckit-analyze` I1: an earlier edit undercounted its own enumeration as
  "4"; `core.agent_protocol_evidence.TERMINAL_RESOLUTIONS` remains a real,
  independently-importable site even after T003 makes it an alias, and T025
  checks it as the 5th). `agent evidence
  add` is **excluded from this check by construction, not tested
  transitively**: verified against `handle_agent_evidence` and the evidence
  functions it calls (`record_reply_evidence`, `record_validation_evidence`,
  `record_evidence_profile` in `core/workflow.py`), none of which reference
  any resolution/disposition value or the shared constant — it records
  reply/validation/profile evidence only, with no vocabulary surface to
  align (correction found by `/speckit-analyze` E1: an earlier draft
  incorrectly claimed "transitive" coverage through a reliance that does not
  exist in the code — FR-006a/FR-006c's "no capability loss" for `agent
  evidence add` still holds; there is simply nothing to check here). Carve-outs
  per FR-006b for the 4 checked sites: `trivial` (`agent resolve`-only) and
  `defer` (`submit-action`-only) are excluded from the strict equality check.
  No prior capability of any command is lost.
- **SC-005**: **100%** of a representative set of today's mode-preset
  invocations continue to produce equivalent resolution outcomes and evidence
  during the deprecation window, each emitting a visible deprecation notice.
- **SC-006**: Reading the command help lets an agent identify the valid way to
  express any target intent **without** triggering a trial-and-error runtime
  rejection (verified by the discoverability acceptance scenario).

## Assumptions

- v1 covers the full user-facing resolution/evidence surface —
  `agent resolve`, `agent evidence add`, and `submit-action` — under one
  orthogonal axis model (clarified 2026-07-08). `agent resolve` is the locus of
  issue #204 and the accretion, where the emergent conflict matrix is removed;
  `submit-action` and `agent evidence add` are aligned to the same
  disposition/selection/evidence vocabulary (they lack that matrix, so their
  change is consistency alignment). The low-level protocol commands (`classify`,
  `next`, `submit`, `publish`) remain the stable, already-orthogonal substrate
  and are not redesigned.
- Backward compatibility uses a **deprecation window with aliases** (retired
  mode-preset flags map to axis equivalents and warn), not a hard cutover — this
  follows constitution Principle II ("CLI Is The Stable Public Interface")
  that public contracts are preserved or explicitly versioned.
- "Converge necessary commands" means reducing the mode-preset surface and
  making the axes uniform; it does not mean removing genuine capabilities
  (batch, homogeneous decline, stale handling all remain expressible as axis
  combinations).
- Exact new flag names / positional-vs-flag shape are an implementation/plan
  concern, not fixed by this spec; the spec fixes the **axes and their
  composability**, not their surface syntax.
- This is a public CLI/agent contract change; version bumping and skill-doc
  updates ship together with the runtime change (testable-contracts rule).

## Dependencies

- Issue #204 (`agent resolve: disposition modes not orthogonal with item_id`) —
  this feature is its resolution.
- The existing resolution protocol (`classify` → `next`/lease → `submit` →
  `publish`) and `final-gate`, which must retain identical guarantees.
- The Status-to-Action Map and machine-summary contract, which must be preserved
  or explicitly versioned.
