# Feature Specification: Core-Path-Anchored Complexity Reduction

**Feature Branch**: `025-complexity-reduction`  
**Created**: 2026-07-01  
**Status**: Verified
**Input**: User description: "反向 analyze:从 core 用户旅程倒推,找出不在主路径上的每一层,逐个评估删除影响,输出可删除层清单与分阶段收敛路线图。保留 OpenTelemetry。"

## Clarifications

### Session 2026-07-01

- Q: Do `constitution.md` and `AGENTS.md` change as part of 025, and how far? → A: Option A — amend both **in-scope and blocking**: relax Principles VI/VIII/IX to match the reduced architecture, add a "complexity-budget / minimal-viable" principle reclassifying the heavy MUSTs as **blast-radius-triggered**, and update AGENTS.md's Architecture Preflight Gate in lockstep (constitution MAJOR version bump).
- Q: What is the non-negotiable floor after the reduction? → A: The **core journey** (findings → classify → reply + resolve → final-gate) **plus OpenTelemetry** tracing is the protected baseline; it MUST NOT be casually expanded — any new subsystem/layer beyond it requires an explicit blast-radius justification recorded against the complexity budget.
- Q: Is a sweep of all historical deprecated/legacy/compat code in scope? → A: Option A — yes, an **evidence-gated sweep** driving remaining `deprecated`/`legacy`/`compat`/`shim` code to **zero**; each item removed only after grep-confirming **no live consumer**; any still-referenced **public-contract shim** is removed via a **versioned** change (Compatibility Policy), not kept indefinitely.
- Q: Must the packaged skill (`skill/`) be updated in the same reduction? → A: Yes — `skill/` (`SKILL.md`, `references/*`, `agents/openai.yaml`, status-to-action guidance) is updated **in lockstep** so no installed guidance references a removed command or the removed architecture; the skill change ships in the same versioned change.
- Q: Does "keep OpenTelemetry" mean protecting the OTel code even as an empty shell? → A: No. OpenTelemetry is retained as **observability of surviving business functionality** (it rides with the business feature — e.g. the core-journey CLI-invocation span). The system MUST NOT keep an empty-shell OTel wrapper just to satisfy "keep OTel", and MUST delete any OTel plumbing that only instrumented removed subsystems. Business functionality comes first; OTel is kept **where and because** it observes live functionality.

## User Scenarios & Testing *(mandatory)*

This feature is a **reduction**: the product accreted layers (event-sourcing
kernel, evaluation plane, reversible-migration framework, an internal telemetry
attribution cluster, multi-agent orchestration) around a simple core — an AI
agent resolving GitHub PR review threads. The core journey that MUST survive
every story is: **agent opens a PR → gets findings → classifies → replies +
resolves each thread → proves completion with `final-gate`.** Each story removes
one layer that is *not* on that path and verifies the core still works.

### User Story 1 - Remove the self-referential migration meta-layer (Priority: P1) 🎯 MVP

As the maintainer, I want to delete the consolidation framework and the
evaluation plane — the two subsystems whose only job is to *measure* and *safely
migrate* a duplication that has not been retired — so the codebase stops carrying
infrastructure-for-infrastructure that no core command touches.

**Why this priority**: Highest value-to-risk. Neither subsystem is on the core
path; each is reached only through its own advanced CLI command. Their
deprecation inventory is entirely `removable=False` — they have produced no
actual removal, only scaffolding. Deleting them reclaims the largest low-risk
weight and eliminates an entire meta-layer.

**Independent Test**: Delete the two packages + their command handlers + CLI
wiring, run the full test suite and a `review → resolve → final-gate` smoke run;
the core journey completes unchanged and `final-gate` still passes.

**Acceptance Scenarios**:

1. **Given** the consolidation and evaluation subsystems exist, **When** they and
   their advanced commands are removed, **Then** `review`, `address`, `threads`,
   `findings`, `agent`, and `final-gate` behave identically and the suite is green.
2. **Given** `final-gate` optionally called the evaluation manifest writer,
   **When** that fail-open call is removed, **Then** `final-gate` pass/fail truth
   is unchanged (the call never affected the result).
3. **Given** the advanced commands were a public surface, **When** they are
   removed, **Then** the removal is a documented, version-bumped CLI-contract
   change (they no longer appear in help/metavar and unknown-command errors list
   the reduced set).
4. **Given** the packaged skill references the removed commands/architecture,
   **When** the commands are removed, **Then** `skill/` (`SKILL.md`, `references/*`,
   `agents/openai.yaml`, status-to-action guidance) is updated in the same change
   so no installed guidance points an agent at a removed command.

---

### User Story 2 - Collapse the dual review state-engine into one (Priority: P1)

As the maintainer, I want exactly one authoritative review state-transition
engine, so the system stops running two implementations of the same logic side
by side.

**Why this priority**: This is the root duplication spec 016 already named. The
imperative `workflow.py`/`workflow_matching.py` path is live and authoritative;
the event-sourced kernel's review projections/policies/commands are a parallel
re-implementation wired to nothing except the (now-removed) parity observer. The
gate slice of the kernel is load-bearing and stays.

**Independent Test**: Keep `workflow.py` as the single engine; keep
`runtime_kernel/final_gate.py` (used by the gate); delete the kernel's
review-state-machine modules; run the suite and the core smoke run — reply,
resolve, and gate results are identical.

**Acceptance Scenarios**:

1. **Given** two engines exist, **When** the kernel review-state-machine slice is
   removed, **Then** `review`/`agent resolve`/`final-gate` still produce the same
   thread states, reply/resolve side effects, and gate verdicts.
2. **Given** `core/gate.py` depends on `runtime_kernel/final_gate.py`, **When**
   the reduction runs, **Then** that gate dependency remains intact and the
   final-gate math is unchanged.
3. **Given** the removed slice had contract tests, **When** it is deleted,
   **Then** its tests are deleted with it and no remaining test imports it.

---

### User Story 3 - Sweep dead, legacy, and duplicate scraps to zero (Priority: P2)

As the maintainer, I want the small accreted scraps gone AND all remaining
historical deprecated code driven to zero, so the CLI dispatcher and GitHub layer
read as one clear path with no lingering `# deprecated` residue.

**Why this priority**: Zero-to-low blast radius, immediate clarity. Includes the
dead `_legacy_module()` stub, the retired-command rejection table, the four
overlapping command-set constants, and the alternate `ReplyPoster`/`ThreadResolver`
wrappers that the live publish path bypasses. It also finishes the job: after US1
removes the consolidation package (which holds most markers), the remaining
`deprecated`/`legacy`/`compat`/`shim` code (e.g. `workflow.py` legacy branches, the
telemetry re-export shim) is swept to zero — each item only after confirming no
live consumer, and any public-contract shim only via a versioned change.

**Independent Test**: Remove each scrap, confirm no remaining reference (grep),
run the suite; unknown-command handling and reply/resolve still behave correctly.

**Acceptance Scenarios**:

1. **Given** `UNSUPPORTED_LEGACY_COMMANDS` only prints a rejection, **When** it is
   removed, **Then** an unknown command still fails with a clear error listing
   supported commands.
2. **Given** `ReplyPoster`/`ThreadResolver` are not on the live publish path,
   **When** they are removed, **Then** `publisher.py` reply/resolve is unaffected
   and no test depends on the removed classes.
3. **Given** four overlapping command-set constants, **When** they are collapsed,
   **Then** flag/routing behavior for every command is unchanged.
4. **Given** historical `deprecated`/`legacy`/`compat`/`shim` code remains after
   US1, **When** the sweep runs, **Then** `(src/ grep hits) − (entries in
   `.deprecated-allowlist.txt`)` equals zero, each removal confirmed to have no live
   consumer, and any public-contract shim removed via a versioned change.

---

### User Story 4 - Shrink internal telemetry (keep OpenTelemetry) and demote multi-agent (Priority: P3)

As the maintainer, I want the internal efficiency-metrics telemetry cluster
reduced to a thin, optional, off-by-default hook and multi-agent orchestration
made an optional extra — **while keeping OpenTelemetry tracing fully intact** — so
the largest remaining weight comes down without losing observability or the
single-agent path.

**Why this priority**: Larger surface and more test mass, so it goes last. Bounded
by a hard constraint: the OTLP process tracing must not be touched.

**Independent Test**: Preserve the OpenTelemetry span/export path; reduce the
internal telemetry cluster to a minimal optional hook; run the suite and confirm
traces still emit and core review/resolve/gate stays fail-open when the internal
telemetry is absent.

**Acceptance Scenarios**:

1. **Given** OpenTelemetry rides with surviving business functionality, **When**
   internal telemetry is shrunk, **Then** the OTLP span still traces the surviving
   core CLI invocation (live observability), and **no empty-shell OTel wrapper** or
   OTel plumbing that only served a removed subsystem is retained.
2. **Given** the internal efficiency-metrics cluster is reduced, **When** it is
   absent or disabled, **Then** `review`/`resolve`/`final-gate` complete
   (fail-open) and only the audit-summary efficiency text degrades gracefully.
3. **Given** multi-agent orchestration is demoted, **When** an agent uses the
   default single-agent path, **Then** it works without the orchestrator present.

---

### User Story 5 - Align governance with the reduced architecture and set the floor (Priority: P0 — mandatory predicate, highest)

As the maintainer, I want the constitution and AGENTS.md amended so the reduced
architecture is the new law and cannot silently regrow, so the deletions are
legal by the project's own governance and future features cannot re-mandate the
removed layers.

**Why this priority**: **P0 — it gates every other story.** Under the current
constitution, US1–US4 violate Principles IX/VI/VIII and each spec's mandatory
Constitution Check fails, so no reduction stage may merge before this lands. It is
also the root remedy: without a complexity budget, the deleted layers grow back on
the next feature. Sequencing: **US5 first**, then US1 → US4.

**Independent Test**: Review the amended constitution + AGENTS.md; confirm the
reduced architecture (single imperative engine, optional orchestration, minimal
internal telemetry + preserved OpenTelemetry) violates no MUST, and that a
defined protected baseline forbids casual expansion.

**Acceptance Scenarios**:

1. **Given** Principles VI/VIII/IX mandate the kernel/orchestrator/heavy telemetry,
   **When** they are amended, **Then** US1–US4 no longer violate any MUST and the
   constitution version is bumped (MAJOR) with a Sync Impact Report.
2. **Given** the accretion engine is the "every change satisfies 9 heavy MUSTs"
   rule, **When** a complexity-budget / minimal-viable principle is added, **Then**
   the heavy principles apply only when blast radius triggers them, and a
   one-thread reply change is explicitly exempt from event-sourcing / preflight.
3. **Given** the core journey + OpenTelemetry is the protected baseline, **When**
   any future feature proposes a new subsystem beyond it, **Then** it must record an
   explicit blast-radius justification against the complexity budget or be rejected.
4. **Given** AGENTS.md's Architecture Preflight Gate forces heavy process on all
   runtime/telemetry/lease changes, **When** it is updated, **Then** the gate fires
   only by blast-radius trigger, consistent with the amended constitution.

---

### Edge Cases

- A removed advanced command (`evaluation`, `consolidation`) invoked after removal
  must fail as an unknown command, not error obscurely.
- Removing the evaluation manifest writer must not change any `final-gate` verdict
  (it was fail-open by contract).
- Keeping `runtime_kernel/final_gate.py` while deleting sibling kernel modules
  must not break the gate's imports.
- Shrinking internal telemetry must keep the OpenTelemetry span/export path working
  **for the surviving core journey**, but must NOT preserve an empty-shell OTel
  wrapper or OTel plumbing that only instrumented a removed subsystem.
- If the kernel-commitment decision is later reversed (see Assumptions), US2 must
  be revisited rather than silently half-applied.
- Every stage must leave the suite green before the next begins (no partial engine).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The reduction MUST preserve the core journey unchanged: `review`,
  `address`, `threads`, `findings`, `agent` (classify/reply/resolve), and
  `final-gate`, including reply/resolve GitHub side effects and gate verdicts.
- **FR-002**: The system MUST remove the consolidation subsystem
  (`core/consolidation/`, `commands/consolidation.py`), its CLI wiring, its
  protocol reason codes, and its tests.
- **FR-003**: The system MUST remove the evaluation subsystem
  (`core/evaluation/`, `commands/evaluation.py`), its CLI wiring, and its tests,
  including the fail-open evaluation-manifest call in `final-gate`, without
  changing any `final-gate` verdict.
- **FR-004**: The system MUST retain exactly one authoritative review
  state-transition engine (`workflow.py`/`workflow_matching.py`) and remove the
  kernel's parallel review-state-machine modules, while KEEPING
  `runtime_kernel/final_gate.py` on which `core/gate.py` depends.
- **FR-005**: The system MUST remove dead/legacy scraps: the `_legacy_module()`
  stub, the `UNSUPPORTED_LEGACY_COMMANDS` rejection table, redundant overlapping
  command-set constants (collapsed to one), and the unused
  `ReplyPoster`/`ThreadResolver` wrappers — each only after confirming no live or
  test reference remains.
- **FR-006**: The system MUST keep OpenTelemetry as **observability of surviving
  business functionality**, not as an independently protected artifact. Where the
  core journey survives, its OTLP tracing (root span in `telemetry.py` +
  `__main__.py` and the export path) MUST keep working. The system MUST NOT retain
  an empty-shell OTel wrapper solely to satisfy "keep OTel", and MUST remove any
  OTel plumbing/instrumentation that only served a removed subsystem. OTel is kept
  **where and because** it traces live functionality — business function first.
- **FR-007**: The system MAY shrink the internal efficiency-metrics telemetry
  cluster to a minimal optional hook; core review-resolution flows MUST remain
  fail-open when internal telemetry is absent or disabled.
- **FR-008**: The system MUST treat removal of public advanced CLI commands as a
  documented, versioned CLI-contract change (help text, metavar, and the
  supported-command set updated together; version bumped).
- **FR-009**: Each stage MUST be independently shippable and leave the full test
  suite green and `ruff` clean before the next stage begins; no stage may leave
  the runtime with a half-removed engine or a dangling import.
- **FR-010**: The reduction MUST NOT remove any layer that is transitively
  load-bearing on the core path (`agent_protocol`, `leases`, `agent_batch`,
  `github/client.py`, `publisher.py`, `session`, `gate`, `runtime_kernel/final_gate`).
- **FR-011**: Removal of a subsystem MUST also remove its dedicated tests, docs,
  and any skill-guidance references in the same change (no orphaned references).
- **FR-012**: The system MUST record a complexity-budget governance principle so
  the removed layers do not silently regrow (see FR-013, Constitution Alignment).
- **FR-013**: Feature 025 MUST amend `.specify/memory/constitution.md` and
  `AGENTS.md` **in-scope** so the reduced architecture violates no MUST: relax
  Principles VI (multi-agent), VIII (telemetry contract), and IX (runtime kernel)
  to **blast-radius-triggered** scope, add a complexity-budget / minimal-viable
  principle, and update the AGENTS.md Architecture Preflight Gate in lockstep. The
  constitution version MUST bump (MAJOR) with a Sync Impact Report.
- **FR-014**: The reduction MUST define a **protected baseline** — the core journey
  (findings → classify → reply + resolve → final-gate) plus the OpenTelemetry
  observability **of that journey** (OTel rides with the surviving business
  functionality, per FR-006; not a standalone shell) — as the non-negotiable floor.
  Removing anything in the baseline is forbidden;
  adding any new subsystem/layer beyond it MUST carry an explicit blast-radius
  justification recorded against the complexity budget.
- **FR-015**: Governance amendments (FR-013) are **P0 — the legal predicate** of the
  reduction and MUST land **before** any of US1–US4; no reduction stage may be
  merged while it still violates the unamended constitution.
- **FR-016**: The reduction MUST sweep remaining historical deprecated code to
  zero: after US1, `(all src/ grep hits for deprecated/legacy/compat/shim) − (the
  enumerated allowlist)` MUST equal zero. The **baseline allowlist** is an explicit,
  justified, enumerated list captured at `specs/025-complexity-reduction/.deprecated-allowlist.txt`
  (each retained match with a one-line reason, e.g. current public Compatibility
  Policy wording) so the gate is reproducible. Each removal MUST be gated on
  grep-confirmed absence of a live consumer; a still-referenced public-contract
  shim MUST be removed via a versioned change (Compatibility Policy), not retained.
- **FR-017**: The packaged skill (`skill/`: `SKILL.md`, `references/*`,
  `agents/openai.yaml`, status-to-action guidance) MUST be updated in lockstep with
  every removal so no installed guidance references a removed command or the removed
  architecture; the skill change ships in the same versioned change and preserves
  the Thin Adapter / Behavioral Policy Layer boundary.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: Core session state, GitHub reply/resolve side effects,
  and `final-gate` remain the deterministic owners and are unchanged. Removed
  layers (consolidation/evaluation) never owned review-resolution truth.
- **Runtime Kernel Model**: `final-gate` continues to derive its verdict from
  `runtime_kernel/final_gate.py` (facts → projection → policy). The removed kernel
  review-state-machine slice was a non-authoritative duplicate; deleting it
  *reduces* state space rather than changing runtime truth.
- **CLI / Agent Contract Impact**: Core commands, machine summaries, reason codes,
  wait states, and exit codes are preserved. Removing advanced commands
  (`evaluation`, `consolidation`) is a versioned public-contract change per the
  Compatibility Policy; the Status-to-Action Map for core commands is untouched.
- **Evidence Requirements**: Evidence for verify/classify/reply/resolve/gate is
  unchanged — it lives in the core path, not in the removed layers.
- **Packaged Skill Boundary**: `skill/` stays a thin adapter and is updated in
  lockstep (FR-017): every reference to a removed command or removed architecture in
  `SKILL.md`, `references/*`, `agents/openai.yaml`, and the status-to-action guidance
  is pruned in the same versioned change. No business logic moves.
- **External Intake Replaceability**: The Normalized Findings Contract and intake
  agnosticism are untouched (`intake/` stays).
- **Telemetry Evidence Boundary**: OpenTelemetry tracing is preserved. Internal
  telemetry, if shrunk, stays observed evidence and fail-open; it never becomes
  review-resolution state. No coverage/attribution guarantee for *core* flows is
  weakened.
- **Architecture Plateau Risk**: This feature is the plateau *remedy* — it removes
  duplicate ownership and decision surfaces (dual engine, meta-migration layer)
  and adds no new branches, flags, fallbacks, or artifact-backed truth. It also
  **amends the constitution itself** (Principles VI/VIII/IX → blast-radius-triggered;
  new complexity-budget principle) so the reduced architecture becomes the governing
  law and cannot regrow; see FR-013. The core journey + OpenTelemetry is fixed as
  the protected baseline (FR-014).
- **Fail-Fast Behavior**: Removed commands fail loudly as unknown; a dangling
  import or half-removed engine must fail the build/suite, not degrade silently.

### Key Entities

- **Core journey**: the irreducible path (findings → classify → reply → resolve →
  final-gate) that every stage must preserve.
- **Deletable layer**: an accreted subsystem off the core path, scored by blast
  radius, with a keep/shrink/cut verdict.
- **Reduction stage**: an independently shippable removal unit with its own
  green-suite gate.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After US1, `core/consolidation/` and `core/evaluation/` and their
  commands are absent, and the full suite is green with the core smoke run
  passing. (~1,900 + ~1,770 LOC src+test removed.)
- **SC-002**: `final-gate` verdicts are byte-for-byte identical before and after
  removing the evaluation manifest call on representative fixtures.
- **SC-003**: After US2, exactly one review state-transition engine remains;
  grep finds no live import of the removed kernel review-state-machine modules;
  reply/resolve/gate outputs are unchanged. (~1,000 LOC removed.)
- **SC-004**: Total source lines removed across US1–US3 is at least 4,500
  (src+test), with zero change to core-command machine-summary contracts.
- **SC-005**: OpenTelemetry still traces the surviving core CLI invocation (one root
  span per invocation) after every stage — live observability, not an empty shell,
  and no OTel plumbing that only served a removed subsystem remains (verified by the
  existing tracing test/inspection).
- **SC-006**: Core review/resolve/final-gate complete successfully with internal
  telemetry disabled or absent (fail-open preserved).
- **SC-007**: Every stage leaves the suite green and `ruff` clean independently;
  no stage is merged with a dangling import or half-removed engine.
- **SC-008**: Public-command removals are reflected in help/metavar and a version
  bump in the same change.
- **SC-009**: After US5, `constitution.md` contains no unconditional MUST that
  US1–US4 violate; Principles VI/VIII/IX are blast-radius-scoped, a complexity-budget
  principle exists, the version is bumped (MAJOR) with a Sync Impact Report, and
  AGENTS.md's Preflight Gate matches.
- **SC-010**: A documented protected baseline (core journey + OpenTelemetry) exists,
  and the governance forbids adding any new subsystem without a recorded blast-radius
  justification (verifiable from the new principle's text).
- **SC-011**: After the reduction, `(all src/ grep hits for
  deprecated/legacy/compat/shim) − (entries in `.deprecated-allowlist.txt`)` equals
  zero; no removed item had a live consumer; any public-contract shim was removed via
  a versioned change.
- **SC-012**: `skill/` contains zero references to any removed command or removed
  architecture; the installed skill instructs only the reduced surface, shipped in
  the same versioned change.

## Assumptions

- **Kernel-fate default = abandon the kernel-as-state-engine.** The recommended
  and assumed direction is to keep `workflow.py` as the single authoritative
  engine and delete the kernel's review-state-machine slice (US2), rather than
  committing to the kernel by deleting `workflow.py`. This matches the owner's
  simplification intent. The alternative (finish the kernel migration, delete
  `workflow.py`) is a scope toggle that would replace US2's direction; it is not
  assumed here.
- **OpenTelemetry is kept** (owner directive); only the internal efficiency-metrics
  telemetry cluster is a shrink candidate, and only at P3.
- Feature 024 (consolidation) and 023 (evaluation) are present on this branch and
  are removed as live code, not merely abandoned on an unmerged branch.
- `host_telemetry` and `orchestrator` are off the core path; `host_telemetry` may
  be folded/dropped with telemetry (P3) and `orchestrator` demoted to optional;
  neither blocks US1–US3.
- Removal is staged and reversible via version control; each stage is a separate,
  independently green change so a regression is isolated to one stage.
- Per clarification (Session 2026-07-01), the governance change is **in-scope and
  blocking** (US5 / FR-013), not a follow-up: `constitution.md` + `AGENTS.md` are
  amended as the legal predicate of the reduction, and the core journey +
  OpenTelemetry is fixed as the protected baseline (FR-014) that cannot be casually
  expanded.
