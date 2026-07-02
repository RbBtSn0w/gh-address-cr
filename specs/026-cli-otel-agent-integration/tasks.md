# Tasks: CLI OpenTelemetry Instrumentation for AI Agent Scenarios (v1 MVP)

**Input**: Design documents from `/specs/026-cli-otel-agent-integration/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-otel-span-attributes.md

**Scope (confirmed)**: v1 MVP = **Dimension 1** (execution + new `safe_command_args`
+ exit.code/error.type) · **Dimension 2** (dormant `TRACEPARENT` G-1,
`process.parent_pid`, **Tier 2 passive session correlation FR-011**) ·
**Dimension 3** (`gen_ai.operation/tool.name/tool.call.arguments`) · **Tier 1 VCS
GitHub-PR mapping FR-012** (plain PR#+provider, hashed repo, no plain owner/URL) ·
`_incubating` semconv pins (G-4). **Excluded (deferred)**: G-2 `--traceparent`
flag + skill instruction, G-3 `gen_ai.tool.call.result`.

**Tests**: REQUIRED (telemetry + privacy change) — TDD, failing tests first per story.

**Single-span constraint**: all attributes attach to the existing
`gh-address-cr.cli` span in `src/gh_address_cr/__main__.py` (FR-009). Shared files
`__main__.py`, `telemetry.py`, `core/telemetry_safety.py`, `core/otel_semconv.py`
are touched by multiple stories → those tasks are sequential (not `[P]`) across stories.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

- [x] T001 Run `pip install -e .` then `python3 -m unittest discover -s tests` and confirm the suite passes before changes (baseline).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared semconv constant surface (G-4) used by all stories, incl. VCS + Tier 2 keys.

- [x] T002 [P] Create `src/gh_address_cr/core/otel_semconv.py` re-exporting the pinned `_incubating` constants: process (`PROCESS_EXECUTABLE_NAME`, `PROCESS_PID`, `PROCESS_EXIT_CODE`, `PROCESS_COMMAND_ARGS`, `PROCESS_PARENT_PID`), gen_ai (`GEN_AI_OPERATION_NAME`, `GEN_AI_TOOL_NAME`, `GEN_AI_TOOL_CALL_ARGUMENTS`, `GEN_AI_CONVERSATION_ID`, `GEN_AI_AGENT_NAME`), vcs (`VCS_CHANGE_ID`, `VCS_PROVIDER_NAME`, `VCS_REPOSITORY_NAME`, `VCS_CHANGE_STATE`), and `ERROR_TYPE`; module docstring records the pinned SDK version (G-4/R-004).
- [x] T003 [P] Create `tests/test_otel_semconv_pins.py` that imports `otel_semconv` (guards `_incubating` import paths, V1) and asserts each constant's literal string value (e.g. `VCS_CHANGE_ID == "vcs.change.id"`, `GEN_AI_CONVERSATION_ID == "gen_ai.conversation.id"`, `PROCESS_PARENT_PID == "process.parent_pid"`) so upstream rename (import fails) or value churn (assert fails) both fail loud. Run in the project venv.

**Checkpoint**: Constant surface pinned; stories can begin.

---

## Phase 3: User Story 1 — Prove what the CLI actually received (Priority: P1) 🎯 MVP

**Goal**: Execution identity, sanitized full argv, exit code, bounded error type on the single span — forensics without reproduction.

**Independent Test**: success + failing + sensitive-arg run under in-memory exporter; assert identity/exit/redacted-args, single span, no raw secret.

### Tests for User Story 1 (write first, ensure they FAIL)

- [x] T004 [P] [US1] In `tests/test_cli_otel_execution.py`, test a successful run records `process.executable.name`, `process.pid`, `process.exit.code == 0`, no `error.type`; assert `len(exported_spans) == 1` and `span.kind == SpanKind.INTERNAL` (C-1/C-2/C-3, G1/G2).
- [x] T005 [P] [US1] In `tests/test_cli_otel_execution.py`, test error semantics (C-3, F1): (a) a propagated exception records synthetic `process.exit.code == 1` + a bounded-set `error.type` (`"keyboard_interrupt"`/`"timeout"`/`"_OTHER"`) + span status ERROR; (b) a **non-zero status return** (e.g. exit 6 `WAITING_FOR_EXTERNAL_REVIEW`, exit 2 needs-action) records that exit code but **no** `error.type` and non-ERROR status; (c) success records exit 0, no `error.type`.
- [x] T006 [P] [US1] In `tests/test_telemetry_safety_command_args.py`, test `safe_command_args` redacts token/credential/username/unnecessary-abs-path tokens to `"[redacted]"`, redacts only the value half of `--flag=secret`, preserves argument position, never emits a raw secret (C-4).

### Implementation for User Story 1

- [x] T007 [US1] Add `safe_command_args(argv: list[str]) -> list[str]` to `src/gh_address_cr/core/telemetry_safety.py`, reusing `_contains_token_marker`, `_contains_private_identifier`, `_looks_like_unnecessary_absolute_path`; per-token redaction to `"[redacted]"` (position-preserving); `--flag=value` redacts only the value half.
- [x] T008 [US1] Extend `run_traced` in `src/gh_address_cr/telemetry.py` to record `process.exit.code` (`otel_semconv.PROCESS_EXIT_CODE`) always — honest returned int on normal return (incl. non-zero **status** codes), synthetic `1` on propagated exception before re-raising (U1). Set `error.type` + span status ERROR **only on a propagated exception** (crash), from the enumerated literals `"keyboard_interrupt"`/`"timeout"`/`"_OTHER"`; a non-zero *return* MUST NOT set `error.type` (F1, Principle VIII — no inflated failure counts). Widen the `attributes` annotation to accept `Sequence[str]` (U2); preserve `SystemExit` handling (a zero `SystemExit` is success; a non-zero `SystemExit` is a status return, not an error). `run_traced` is CLI-entrypoint-only (U3).
- [x] T009 [US1] In `src/gh_address_cr/__main__.py`, set `process.executable.name` (basename of `sys.argv[0]` or `"gh-address-cr"`), `process.pid` (`os.getpid()`), and `process.command_args` from the processed argv — `safe_command_args([sys.argv[0]] + (argv if argv is not None else sys.argv[1:]))` (U1).

**Checkpoint**: US1 fully functional (MVP core).

---

## Phase 4: User Story 2 — Correlate a CLI run back to the agent (Priority: P2)

**Goal**: Passive session grouping (Tier 2, works today) + `process.parent_pid` breadcrumb + dormant `TRACEPARENT` nesting — all fail-open.

**Independent Test**: run with/without `CLAUDE_CODE_SESSION_ID`, with well-formed/malformed `TRACEPARENT`, and a bare run; assert conversation grouping, parent recovery vs root fallback, ppid, exit code unchanged throughout.

### Tests for User Story 2 (write first, ensure they FAIL)

- [x] T010 [P] [US2] In `tests/test_cli_otel_context.py`, test a well-formed `TRACEPARENT` env makes the span a child of the injected trace/span id; malformed/absent → root span, exit code unchanged (C-7/C-8, fail-open).
- [x] T011 [P] [US2] In `tests/test_cli_otel_context.py`, test `process.parent_pid == os.getppid()` and does not alter the span's trace id; if `getppid` raises, the attribute is omitted and the span still emits (C-6, U2).
- [x] T012 [P] [US2] In `tests/test_cli_otel_context.py`, test Tier 2: with `CLAUDE_CODE_SESSION_ID` set, two invocations carry an identical `gen_ai.conversation.id` (+ `.source == "CLAUDE_CODE_SESSION_ID"`) and `gen_ai.agent.name` from `AI_AGENT`; with the override `GH_ADDRESS_CR_CONVERSATION_ID` only, it is used; with none set, all three attributes are absent (C-11, FR-011).

### Implementation for User Story 2

- [x] T013 [US2] Add `resolve_parent_context(environ) -> Context | None` to `src/gh_address_cr/telemetry.py` using `TraceContextTextMapPropagator().extract({"traceparent": value})`; return `None` when absent; rely on extract's INVALID-context behavior for malformed values (no exception path).
- [x] T014 [US2] Extend `run_traced` in `src/gh_address_cr/telemetry.py` to accept an optional `parent_context` and pass it to `start_as_current_span(..., context=...)`; behavior unchanged when `None`.
- [x] T015 [US2] Add `detect_agent_session(environ) -> dict[str, str]` to `src/gh_address_cr/core/telemetry_safety.py`: an ordered module-level registry (`CLAUDE_CODE_SESSION_ID` → `GH_ADDRESS_CR_CONVERSATION_ID`) → `gen_ai.conversation.id` + `gen_ai.conversation.id.source`; `AI_AGENT` → `gen_ai.agent.name`; empty dict when none; all values routed through the public-safe path (data-model Entity 4, FR-011).
- [x] T016 [US2] In `src/gh_address_cr/__main__.py`, call `resolve_parent_context(os.environ)` (pass to `run_traced`), set `process.parent_pid` from `os.getppid()` (omit on failure, U2), and merge `detect_agent_session(os.environ)` into the span attributes; inline comment documenting the `TRACEPARENT` path as dormant (R-002) and Tier 2 as the active v1 correlation (R-009).

**Checkpoint**: US1 + US2 independently functional; session grouping works today.

---

## Phase 5: User Story 3 — CLI tool calls in the AI tool-call view (Priority: P3)

**Goal**: `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name`, `gen_ai.tool.call.arguments` (reusing US1 sanitized argv); `tool.call.result` omitted (G-3).

**Independent Test**: invoke under in-memory exporter; assert the three GenAI attrs, arguments == sanitized argv, result absent.

### Tests for User Story 3 (write first, ensure they FAIL)

- [x] T017 [P] [US3] In `tests/test_cli_otel_genai.py`, test the span has `gen_ai.operation.name == "execute_tool"`, a present `gen_ai.tool.name`, and NO `gen_ai.tool.call.result` (C-5).
- [x] T018 [P] [US3] In `tests/test_cli_otel_genai.py`, test `json.loads(span.attributes["gen_ai.tool.call.arguments"]) == list(span.attributes["process.command_args"])` — same sanitized argv, no independently-filtered copy (C-5, A1).

### Implementation for User Story 3

- [x] T019 [US3] Add `derive_tool_name(argv) -> str` (top-level command token, fallback `"gh-address-cr"`) to `src/gh_address_cr/core/telemetry_safety.py`.
- [x] T020 [US3] In `src/gh_address_cr/__main__.py`, set `gen_ai.operation.name = "execute_tool"`, `gen_ai.tool.name` (via `derive_tool_name`), and `gen_ai.tool.call.arguments` (JSON string of the shared sanitized argv); do NOT set `gen_ai.tool.call.result`.

**Checkpoint**: US1–US3 independently functional.

---

## Phase 6: User Story 4 — Group CLI activity by GitHub PR (Priority: P2, privacy-gated)

**Goal**: VCS attributes tie the span to the PR being worked on — plain `vcs.change.id`+`vcs.provider.name`, **hashed** `vcs.repository.name`, conditional `vcs.change.state`, **no plain owner/URL** (FR-012, Tier 1).

**Independent Test**: a PR-scoped run has PR#/provider/hashed-repo and no plain owner/URL; a non-PR run has no `vcs.*`; same repo → same hash across runs.

### Tests for User Story 4 (write first, ensure they FAIL)

- [x] T021 [P] [US4] In `tests/test_telemetry_safety_vcs.py`, test `map_vcs_attributes` returns `vcs.change.id`, `vcs.provider.name == "github"`, and a `vcs.repository.name` that is stable across calls for the same `owner/repo` and differs for a different repo; and returns `{}` when repo/PR are absent.
- [x] T022 [P] [US4] In `tests/test_telemetry_safety_vcs.py`, test the **privacy** guarantee: the returned attributes (and, via an end-to-end span test, all span attributes) contain neither the plain `owner` string nor any `github.com/<owner>/<repo>` URL; `vcs.change.state` is present only when supplied via session data, absent otherwise (C-12).

### Implementation for User Story 4

- [x] T023 [US4] Add `repo_hash(owner_repo: str) -> str` and `map_vcs_attributes(command, repo, pr_number, session) -> dict[str, str]` to `src/gh_address_cr/core/telemetry_safety.py` per data-model Entity 5: plain `vcs.change.id`/`vcs.provider.name=github`; `vcs.repository.name = repo_hash(owner/repo)` (deterministic one-way digest); `vcs.change.state` only if present in `session`; return `{}` for non-PR commands; never emit plain owner or repository URL (FR-012).
- [x] T024 [US4] In `src/gh_address_cr/__main__.py`, parse the invoked command's `owner/repo` + `pr_number` (reuse existing arg parsing) and merge `map_vcs_attributes(...)` into the span attributes; omit for non-PR commands.

**Checkpoint**: US1–US4 independently functional; per-PR grouping without leaking private repo identity.

---

## Phase 7: Polish & Cross-Cutting

- [x] T025 [P] Update `specs/026-cli-otel-agent-integration/quickstart.md` if any attribute name/behavior drifted during implementation; keep dormant-`TRACEPARENT`, Tier 2, and VCS-privacy notes accurate.
- [x] T026 Run `ruff check src tests` and fix lint from the new modules/tests.
- [x] T027 Run `python3 -m unittest discover -s tests` and confirm the full suite (incl. new files + pin test) passes.
- [x] T028 Run CLI smoke checks: `python3 -m gh_address_cr --help` (no new required flags, SC-005) and `DISABLE_TELEMETRY=1 python3 -m gh_address_cr version` (opt-out unaffected, C-8).
- [x] T029 Privacy validation (SC-004 + SC-008): across a sampled sensitive-arg + PR-scoped run, assert no span attribute contains a raw token/credential/username/unnecessary-abs-path, nor the plain repo `owner`/URL.

---

## Dependencies & Execution Order

### Phase dependencies
- Setup (P1) → Foundational (P2) → Stories (P3–P6) → Polish (P7).
- Foundational (T002–T003) blocks all stories (constants used everywhere).

### Story dependencies
- **US1 (P1)**: after Foundational. No dependency on others. **MVP.**
- **US2 (P2)**: after Foundational. T014/T016 touch the same `run_traced`/`__main__` as US1 → run US1 first.
- **US3 (P3)**: after Foundational. Reuses US1 `safe_command_args` (T007) → US1 first.
- **US4 (P2)**: after Foundational. Independent logic (`telemetry_safety` VCS fns) but T024 edits `__main__` → sequence after US1/US2/US3 edits to that file.

### Shared-file serialization (NOT parallel across stories)
- `src/gh_address_cr/telemetry.py`: T008 (US1), T013/T014 (US2).
- `src/gh_address_cr/core/telemetry_safety.py`: T007 (US1), T015 (US2), T019 (US3), T023 (US4) — distinct functions, but same file → sequential edits.
- `src/gh_address_cr/__main__.py`: T009 (US1), T016 (US2), T020 (US3), T024 (US4).
Do these in story-priority order; only `[P]` test files and T002/T003 parallelize freely.

### Within each story
- Tests (fail first) → implementation.

---

## Parallel Example: User Story 1

```bash
Task: "T004 execution-span attributes test in tests/test_cli_otel_execution.py"
Task: "T006 safe_command_args redaction tests in tests/test_telemetry_safety_command_args.py"
```

---

## Implementation Strategy

### MVP First (US1 only)
Phase 1 → 2 → 3 (US1). **STOP & VALIDATE** — US1 alone delivers the forensic core. Ship if ready.

### Incremental Delivery
US1 (forensics) → US2 (Tier 2 session correlation + ppid + dormant TRACEPARENT) → US3 (GenAI vocabulary) → US4 (per-PR grouping, privacy-hashed). Each adds value independently. G-2/G-3 remain deferred.

---

## Notes
- Every span attribute uses `otel_semconv` constants (G-4), never string literals.
- `process.command_args` and `gen_ai.tool.call.arguments` share one `safe_command_args` result (FR-002/FR-007).
- Privacy is enforced by tests: no raw secret (C-4/SC-004) and **no plain owner/URL** (C-12/SC-008); `vcs.repository.name` is the hash only.
- Telemetry stays fail-open: no task lets a telemetry/env/VCS failure change the CLI exit code (C-8).
- Commit after each task or logical group; do not stage/commit without explicit request.

---

## Phase 8: Convergence

> Appended by `/speckit-converge` (2026-07-02). Assessment of implemented code vs
> spec/plan/data-model intent. Both findings are MEDIUM (output is currently
> correct and public-safe; these close code↔spec divergences). Complete via
> `/speckit-implement`.

- [ ] T030 Reconcile the agent-session env precedence contradiction per FR-011 / data-model Entity 4 (contradicts): `detect_agent_session` and `test_cli_otel_context.py::test_agent_session_correlation_case_b_both` make `GH_ADDRESS_CR_CONVERSATION_ID` win over `CLAUDE_CODE_SESSION_ID`, but data-model Entity 4 ("first match wins: CLAUDE_CODE_SESSION_ID → GH_ADDRESS_CR_CONVERSATION_ID") and FR-011 ("from CLAUDE_CODE_SESSION_ID, else …") specify CLAUDE-first. Decide the intended order and align code + test to the data-model registry ordering (or, if override-wins is intended, that is a spec-wording change outside converge's write scope — flag it for a spec edit).
- [ ] T031 De-duplicate CLI identity/session attribute assembly in `src/gh_address_cr/telemetry.py` `run_traced` per plan separation "run_traced = span lifecycle + exit/error; __main__ = attribute assembly" (unrequested): `run_traced` sets `process.executable.name = os.path.basename(sys.executable)` (= "python", incorrect — only masked because `__main__`'s attributes override it afterward) and also re-sets `process.pid`/`process.parent_pid` and re-calls `detect_agent_session`, duplicating `__main__`. Remove the redundant identity/session sets from `run_traced` so it only owns span lifecycle + exit.code/error.type, leaving identity/session/args/gen_ai/vcs assembly to `__main__`; keep the full suite green.
