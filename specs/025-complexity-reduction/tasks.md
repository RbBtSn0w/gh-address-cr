---
description: "Task list for Core-Path-Anchored Complexity Reduction"
---

# Tasks: Core-Path-Anchored Complexity Reduction

**Input**: Design documents from `specs/025-complexity-reduction/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/README.md

**Nature**: This is a **reduction** (deletion + governance amendment), not a new
feature. "Tests" here means the **per-stage green gate** (full `unittest` suite +
`ruff` + core smoke) plus **grep proofs** (no dangling import, zero deprecated
markers, no skill reference to a removed command, protected layers survive) and a
few focused regression assertions. Each stage MUST be independently green before
the next (FR-009).

**Verification harness (run after EVERY stage):**
```bash
.venv/bin/python -m unittest discover -s tests 2>&1 | grep -E "^(Ran|OK|FAILED)"
.venv/bin/ruff check src tests
.venv/bin/python -m gh_address_cr --help
.venv/bin/python -m gh_address_cr final-gate --help
# FR-010 protected-layer SURVIVAL assertion (must succeed after every stage):
.venv/bin/python -c "import gh_address_cr.core.agent_protocol, gh_address_cr.core.leases, gh_address_cr.core.agent_batch, gh_address_cr.github.client, gh_address_cr.core.publisher, gh_address_cr.core.session, gh_address_cr.core.gate, gh_address_cr.core.runtime_kernel.final_gate; print('protected layers OK')"
```

**Ordering (strict):** US5 (P0 governance) → US1 → US2 → US3 → US4 → Polish.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no dependency on incomplete tasks)
- **[Story]**: US1–US5 for story phases; none for Setup/Foundational/Polish
- Exact repo-root paths (`src/gh_address_cr/...`, `.specify/...`, `AGENTS.md`, `skill/...`)

---

## Phase 1: Setup (Baseline & Invariants)

- [ ] T001 Confirm dev env and capture the baseline: `pip install -e .` into `.venv`, run the verification harness, and save the results (record the actual green test count, `ruff` clean, `gh-address-cr --help` output, protected-layer survival OK) to `specs/025-complexity-reduction/.baseline.txt`
- [ ] T002 [P] Snapshot the core-command machine-summary contract (SC-004 "before"): capture `gh-address-cr review/threads/final-gate` help + a representative `final-gate --machine`/summary output to `specs/025-complexity-reduction/.core-contract-before.txt` for byte-for-byte comparison after each stage

**Checkpoint**: baseline recorded; the invariant to protect is captured.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Prove both the removal targets' isolation AND the protected layers' survival before deleting.

- [ ] T003 Produce the dependency proof in `specs/025-complexity-reduction/.isolation-proof.txt`: (a) NEGATIVE — grep confirms `core/consolidation/`, `core/evaluation/` (beyond the `final_gate.py` manifest call), and the `runtime_kernel` review-state-machine modules have **zero importers on the core path** (`cli.py`, `commands/high_level.py`, `core/workflow.py`, `core/gate.py`); (b) POSITIVE (FR-010) — the harness protected-layer import assertion succeeds, proving `agent_protocol`, `leases`, `agent_batch`, `github/client.py`, `publisher.py`, `session`, `gate`, `runtime_kernel/final_gate` import cleanly

**Checkpoint**: removal safety + protected-layer survival confirmed — user story stages may begin.

---

## Phase 3: User Story 5 - Align governance and set the floor (Priority: P0) ⚖️ LEGAL PREDICATE — lands first

**Goal**: Amend `constitution.md` + `AGENTS.md` so the reduced architecture is legal and cannot regrow.

**Independent Test**: The amended constitution has VI/VIII/IX as blast-radius-triggered, a new complexity-budget Principle X, a MAJOR version bump + Sync Impact Report, and AGENTS.md's Preflight Gate is trigger-scoped.

- [ ] T004 [US5] Relax Principle VI (Multi-Agent Coordination) in `.specify/memory/constitution.md` to **blast-radius-triggered** (mandatory only for genuine multi-agent work; single-agent is the default supported path)
- [ ] T005 [US5] Relax Principle VIII (Telemetry) in `.specify/memory/constitution.md`: require OpenTelemetry tracing of live functionality; make attribution/fingerprint/coverage mandatory only for external telemetry ingestion
- [ ] T006 [US5] Relax Principle IX (Runtime Kernel) in `.specify/memory/constitution.md`: `final-gate` keeps fact→projection→policy; broader kernel modeling becomes blast-radius-triggered, not universal
- [ ] T007 [US5] Add Principle X — Minimal Viable / Complexity Budget to `.specify/memory/constitution.md`: define the protected baseline (core journey + OpenTelemetry-of-that-journey) as the floor; any new subsystem beyond it requires a recorded blast-radius justification
- [ ] T008 [US5] Bump the constitution version (MAJOR) and write the Sync Impact Report header in `.specify/memory/constitution.md` (reason, affected principles VI/VIII/IX/+X, dependent templates reviewed)
- [ ] T009 [US5] Update `AGENTS.md`: rewrite the Architecture Preflight Gate to fire only on a blast-radius trigger, and prune AGENTS.md references to the layers being removed (consolidation/evaluation/kernel-review-engine)
- [ ] T010 [US5] Verify US5: `grep -nE "blast.?radius|Complexity Budget|Minimal Viable" .specify/memory/constitution.md` shows the deltas; version bump present; AGENTS.md Preflight Gate is trigger-scoped; run the verification harness (no code changed → still green)

**Checkpoint**: governance is legal for the reductions below. No code removed yet.

---

## Phase 4: User Story 1 - Remove the migration meta-layer (Priority: P1) 🎯 MVP

**Goal**: Delete 024 consolidation + 023 evaluation and their commands; core journey unchanged.

**Independent Test**: Both packages + commands gone; removed commands fail as unknown; suite green; `final-gate` verdict unchanged (SC-002).

- [ ] T011 [US1] Delete `src/gh_address_cr/core/consolidation/` (whole package) and `src/gh_address_cr/commands/consolidation.py`, and remove consolidation-only tests under `tests/consolidation/` and `tests/contract/test_consolidation_cli.py`. **Do NOT delete `tests/contract/test_public_contract_stability.py` wholesale** (it guards the core CLI contract — see T014)
- [ ] T012 [US1] Remove the `consolidation` wiring from `src/gh_address_cr/cli.py` (import, `PUBLIC_COMMANDS` entry, metavar, `_dispatch_consolidation_command`, usage lines) and drop the 6 consolidation reason codes from `src/gh_address_cr/core/protocol_codes.py`
- [ ] T013 [US1] Delete `src/gh_address_cr/core/evaluation/` (whole package) and `src/gh_address_cr/commands/evaluation.py`, and remove its tests (`tests/test_evaluation_cli.py`, `tests/core/evaluation/*`)
- [ ] T014 [US1] Prune + repurpose `tests/contract/test_public_contract_stability.py` (G2): delete the consolidation-additive and evaluation-flag cases; KEEP and update `test_existing_commands_still_parse` (drop `evaluation`) and `test_unknown_command_still_lists_supported_commands` (reduced supported set) as the ongoing **core CLI contract guard** backing SC-002/SC-004
- [ ] T015 [US1] Remove the evaluation import + fail-open `finalize_run_manifest` call from `src/gh_address_cr/commands/final_gate.py` and remove the `evaluation` wiring from `src/gh_address_cr/cli.py` (import, `PUBLIC_COMMANDS`, metavar, `_dispatch_evaluation_command`, usage)
- [ ] T016 [P] [US1] Update `skill/` (`SKILL.md`, `references/*`, `agents/openai.yaml`, status-to-action guidance) **and repo-root docs that describe the public command surface** to remove every reference to `consolidation` and `evaluation` commands in the same change (FR-011, FR-017)
- [ ] T017 [US1] Version bump for the removed `consolidation`/`evaluation` commands (Compatibility Policy) and confirm help/metavar no longer list them
- [ ] T018 [US1] Verify US1: removed commands (`gh-address-cr consolidation status`, `gh-address-cr evaluation rebuild`) exit non-zero as unknown; `final-gate` machine summary is byte-for-byte identical to `.core-contract-before.txt` (SC-002); run the verification harness (green)

**Checkpoint**: MVP — largest low-risk weight removed; core journey intact.

---

## Phase 5: User Story 2 - Collapse the dual review state-engine (Priority: P1)

**Goal**: One authoritative engine (`workflow.py`); delete the kernel review-state-machine slice; KEEP `runtime_kernel/final_gate.py`.

**Independent Test**: Kernel review modules gone with no live importer; `final_gate.py` present; reply/resolve/gate outputs unchanged.

- [ ] T019 [US2] Delete the kernel review-state-machine modules: `src/gh_address_cr/core/runtime_kernel/{projections,policies,commands,events,identity,session_projection}.py` and their dedicated tests under `tests/` (keep `runtime_kernel/final_gate.py` and any module it imports)
- [ ] T020 [US2] Resolve fallout: fix `runtime_kernel/__init__.py` exports and any `final_gate.py` import so the gate still builds without the deleted modules (extract the minimal shared helpers `final_gate.py` needs, if any, rather than resurrecting the engine), and prune any `skill/` **and repo-root architecture** guidance that still describes the deleted kernel review-state-machine / dual-engine model as live (FR-011, FR-017)
- [ ] T021 [US2] Verify US2: `grep -rn "runtime_kernel.projections\|runtime_kernel.policies\|runtime_kernel.commands" src/` returns nothing; `runtime_kernel/final_gate.py` present; run the verification harness (green); `final-gate` verdict unchanged on fixtures

**Checkpoint**: single review engine; the 016-era duplication is gone.

---

## Phase 6: User Story 3 - Sweep dead/legacy/deprecated to zero (Priority: P2)

**Goal**: Remove dead scraps AND drive remaining deprecated markers to zero against an explicit allowlist.

**Independent Test**: `(src/ deprecated-marker hits) − allowlist == 0`; unknown-command handling still works.

- [ ] T022 [US3] Remove dead scraps in `src/gh_address_cr/cli.py`: the `_legacy_module()` stub, the `UNSUPPORTED_LEGACY_COMMANDS` reject table (unknown command already errors), and collapse the 4 overlapping command-set constants (`HIGH_LEVEL_COMMANDS`/`NATIVE_HIGH_LEVEL_COMMANDS`/`PR_SCOPED_IMPLICIT_COMMANDS`/`HIGH_LEVEL_GH_COMMANDS`) into the minimal set actually used
- [ ] T023 [P] [US3] Remove the unused `ReplyPoster` (`src/gh_address_cr/github/replies.py`) and `ThreadResolver` (`src/gh_address_cr/github/threads.py`) after confirming no live or test reference (the live publish path uses `GitHubClient.post_reply`/`resolve_thread`); keep `normalize_threads`
- [ ] T024 [US3] Sweep remaining `deprecated`/`legacy`/`compat`/`shim` code (e.g. `workflow.py` legacy branches, any telemetry re-export shim) — each removed only after grep-confirming no live consumer; any public-contract shim removed via the versioned change. Produce `specs/025-complexity-reduction/.deprecated-allowlist.txt` enumerating every intentionally-retained match with a one-line justification (A1)
- [ ] T025 [US3] Verify US3: `(grep -rniE "deprecated|legacy|compat|shim" src/gh_address_cr --include="*.py") minus the allowlist == 0` (SC-011); unknown-command handling intact; run the verification harness (green)

**Checkpoint**: one clear path, no deprecated residue.

---

## Phase 7: User Story 4 - Shrink internal telemetry + demote orchestration (keep OpenTelemetry) (Priority: P3)

**Goal**: Reduce the internal efficiency-metrics telemetry to a minimal optional hook and demote multi-agent orchestration — **OTel keeps tracing the live core journey; no empty shell**.

**Independent Test**: OTel still traces the core CLI invocation (SC-005); core flows complete with internal telemetry absent (SC-006); single-agent path works without orchestrator.

- [ ] T026 [US4] Shrink the internal telemetry cluster (`src/gh_address_cr/core/telemetry.py` + `telemetry_models/telemetry_reporting/telemetry_safety/telemetry_health.py`) to a minimal optional, off-by-default, fail-open hook; delete attribution/fingerprint/coverage machinery no longer required; remove its now-dead tests
- [ ] T027 [US4] Remove/fold `src/gh_address_cr/core/host_telemetry/` and delete any OTel plumbing/instrumentation that only served a removed subsystem — **without touching** the OTLP root span in `src/gh_address_cr/telemetry.py` + `src/gh_address_cr/__main__.py` (FR-006: OTel of the surviving core journey stays)
- [ ] T028 [US4] Decouple the `final-gate` efficiency-report from the shrunk telemetry so `commands/final_gate.py` degrades the audit-summary text gracefully (fail-open) and never the verdict
- [ ] T029 [US4] Version bump + help/metavar for any removed public `telemetry` subcommand surface (G1, FR-008/SC-008): update `src/gh_address_cr/cli.py` help/metavar and confirm a removed `telemetry` subcommand exits non-zero as unknown while preserved telemetry behavior is unchanged
- [ ] T030 [P] [US4] Demote `orchestrator/` to an optional extra: keep the default single-agent `agent` path working without it; confirm `commands/agent.py`'s lazy `agent orchestrate` import path is the only coupling
- [ ] T031 [P] [US4] Update `skill/` **and repo-root docs that describe telemetry/orchestration behavior** to drop references to the removed telemetry subcommands / removed orchestration guidance in the same change (FR-011, FR-017)
- [ ] T032 [US4] Verify US4: `grep -n "start_as_current_span\|run_traced" src/gh_address_cr/telemetry.py src/gh_address_cr/__main__.py` still present (OTel intact, SC-005); core `review`/`resolve`/`final-gate` complete with internal telemetry disabled/absent (SC-006); single-agent path works; run the verification harness (green)

**Checkpoint**: largest weight down; OpenTelemetry preserved as live observability, no shell.

---

## Phase 8: Polish & Cross-Cutting Verification

- [ ] T033 [P] Confirm SC-004: ≥4,500 LOC (src+test) removed across US1–US3 (`git diff --stat` against the pre-reduction base); core-command machine summaries unchanged vs `.core-contract-before.txt`
- [ ] T034 [P] Confirm SC-012: `grep -rniE "consolidation|evaluation" skill/` returns zero references to removed commands, and `grep -rniE "dual-engine|runtime kernel|kernel review-state-machine|orchestrator" skill/` leaves only intentional surviving references; installed skill instructs only the reduced surface and surviving architecture
- [ ] T035 [P] Final residual docs sweep: confirm repo-root docs (`README.md` and any developer docs) contain no stale references that escaped the story-local doc sync tasks, and reconcile any remaining reduced-surface / single-engine wording gaps
- [ ] T036 Final full verification: `pip install -e .`, `ruff check src tests`, `python3 -m unittest discover -s tests` (green), `python3 -m gh_address_cr --help`, core `review`/`threads`/`final-gate` smoke, protected-layer survival assertion, and confirm the `mypy` strict ratchet does not regress; validate `quickstart.md` scenarios US5→US4 end-to-end

---

## Dependencies & Story Completion Order

```text
Setup (T001-T002) → Foundational (T003) → US5 (P0, T004-T010) → US1 (T011-T018)
  → US2 (T019-T021) → US3 (T022-T025) → US4 (T026-T032) → Polish (T033-T036)
```

- **US5 is P0 and MUST complete before any code-removal story** (FR-015): until the
  constitution is amended, US1–US4 violate Principles IX/VI/VIII.
- **US1 (MVP)** depends only on US5. **US2** depends on US1 — the kernel review-engine's
  only importer is the parity observer inside `core/consolidation/` (024), so removing
  024 first clears the last importer. **US3** depends on US1 (most deprecated markers
  vanish with consolidation). **US4** last (largest surface).
- Each stage's verify task is the merge gate; a failed gate reverts that stage (git).

## Parallel Execution Opportunities

- Setup: T002 ∥ after T001.
- US1: T016 (skill + repo-root command-surface docs) ∥ the code deletions T011–T015; T017/T018 after.
- US3: T023 (ReplyPoster/ThreadResolver) ∥ T022 (cli scraps).
- US4: T030 (orchestrator) ∥ T031 (skill + repo-root telemetry/orchestration docs) after T026–T029.
- Polish: T033, T034, T035 ∥; T036 last.

## Implementation Strategy

- **US5 first (non-negotiable):** legalize the reduction, or every later stage fails
  its own Constitution Check.
- **US1 = MVP:** independently shippable, largest low-risk weight, zero core-path risk.
- **One stage at a time, each independently green** (FR-009); git is the reversal
  mechanism. No stage merges with a dangling import, half-removed engine, empty-shell
  OTel, a removed public command lacking its version bump, or a skill that references
  a removed command.
- **Protected baseline is inviolable:** the core journey + OpenTelemetry-of-that-journey
  survive every stage (survival asserted by the harness); business function first,
  OTel rides with it.
