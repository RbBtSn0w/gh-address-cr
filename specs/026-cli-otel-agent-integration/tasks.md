# Tasks: CLI OpenTelemetry Instrumentation for AI Agent Scenarios (v1 MVP)

**Input**: Design documents from `/specs/026-cli-otel-agent-integration/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-otel-span-attributes.md

**Scope**: v1 MVP per confirmed gate decisions — Dimension 1 (execution span +
new `safe_command_args` sanitizer + exit.code/error.type), `process.parent_pid`,
**dormant** `TRACEPARENT` extraction (G-1), Dimension 3 minus `tool.call.result`,
`_incubating` semconv constants + pin test (G-4). **Excluded**: G-2
(`--traceparent` flag + skill instruction), G-3 (`gen_ai.tool.call.result`).

**Tests**: REQUIRED (telemetry change) — privacy filtering, fail-open context,
attribute presence/absence, low-cardinality error.type. TDD: write failing tests
first within each story.

**Single span constraint**: All attributes attach to the existing
`gh-address-cr.cli` span in `src/gh_address_cr/__main__.py`. No new span/tracer/
exporter (FR-009). `src/gh_address_cr/telemetry.py` and `__main__.py` are shared
by multiple stories → tasks touching them are sequential (not `[P]`) across stories.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

**Purpose**: Confirm a green baseline before any change.

- [ ] T001 Run `pip install -e .` then `python3 -m unittest discover -s tests` and confirm the suite passes before changes (baseline).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared semconv constant surface needed by all stories (G-4).

**⚠️ CRITICAL**: Complete before US1/US2/US3.

- [ ] T002 [P] Create `src/gh_address_cr/core/otel_semconv.py` re-exporting the pinned `_incubating` constants: `PROCESS_EXECUTABLE_NAME`, `PROCESS_PID`, `PROCESS_EXIT_CODE`, `PROCESS_COMMAND_ARGS`, `PROCESS_PARENT_PID` (from `opentelemetry.semconv._incubating.attributes.process_attributes`), `GEN_AI_OPERATION_NAME`, `GEN_AI_TOOL_NAME`, `GEN_AI_TOOL_CALL_ARGUMENTS` (from `...gen_ai_attributes`), and `ERROR_TYPE` (from `opentelemetry.semconv.attributes.error_attributes`); add a module docstring recording the pinned SDK version (G-4).
- [ ] T003 [P] Create `tests/test_otel_semconv_pins.py` that (a) imports `src/gh_address_cr/core/otel_semconv.py` (guards the `_incubating` import paths — see V1) and (b) asserts each re-exported constant's literal string value (e.g. `PROCESS_PARENT_PID == "process.parent_pid"`, `GEN_AI_OPERATION_NAME == "gen_ai.operation.name"`) so upstream rename (import fails) or value churn (assert fails) both fail loud (G-4). Run in the project venv, not system Python.

**Checkpoint**: Constant surface pinned; stories can begin.

---

## Phase 3: User Story 1 — Prove what the CLI actually received (Priority: P1) 🎯 MVP

**Goal**: The single process span carries execution identity, sanitized full
argument vector, exit code, and low-cardinality error type — usable as forensic
evidence without reproducing the run.

**Independent Test**: Run a success command and a failing/sensitive-arg command
under an in-memory exporter; assert identity + exit outcome + redacted args on the
exported span, with no raw secret present.

### Tests for User Story 1 (write first, ensure they FAIL)

- [ ] T004 [P] [US1] In `tests/test_cli_otel_execution.py`, add a test that a successful CLI run records `process.executable.name`, `process.pid`, `process.exit.code == 0`, and NO `error.type` (in-memory `TracerProvider` + `InMemorySpanExporter`). In the same test, assert `len(exported_spans) == 1` and `span.kind == SpanKind.INTERNAL` (enforces FR-009/C-1 single-span + kind; G1/G2).
- [ ] T005 [P] [US1] In `tests/test_cli_otel_execution.py`, add a test that a non-zero return AND a propagated exception each record a non-zero `process.exit.code` (the exception path uses the synthetic `1`) plus a bounded-set `error.type`, both absent on success (U1/A2).
- [ ] T006 [P] [US1] In `tests/test_telemetry_safety_command_args.py`, add tests that `safe_command_args` redacts token/credential/username/unnecessary-abs-path tokens to `"[redacted]"`, redacts only the value half of `--flag=secret`, preserves argument position, and never emits a raw secret.

### Implementation for User Story 1

- [ ] T007 [US1] Add `safe_command_args(argv: list[str]) -> list[str]` to `src/gh_address_cr/core/telemetry_safety.py`, reusing `_contains_token_marker`, `_contains_private_identifier`, `_looks_like_unnecessary_absolute_path`; redact per-token to `"[redacted]"` (position-preserving), handling `--flag=value` by redacting only the value half.
- [ ] T008 [US1] Extend `run_traced` in `src/gh_address_cr/telemetry.py` to record `process.exit.code` (`otel_semconv.PROCESS_EXIT_CODE`) so it is **always present**: use the operation's returned int on normal return, and a **synthetic `1`** on any propagated exception before re-raising (U1) — so FR-003 "every invocation carries exit.code" holds on the exception path. Set `error.type` from an **enumerated bounded set** — `"nonzero_exit"` (non-zero return, no exception), `"keyboard_interrupt"` (`KeyboardInterrupt`), `"timeout"` (`TimeoutError`), else `_OTHER` — never a raw/arbitrary class name (A2/U1 / Principle VIII cardinality guard); leave `error.type` unset on exit 0; preserve existing `SystemExit` handling. Also widen the `attributes` type annotation to accept sequence values (e.g. `Mapping[str, str | bool | int | float | Sequence[str]]`) so `process.command_args` (string[]) type-checks (U2). Note: exit-code recording lives here because `run_traced` is the CLI-entrypoint wrapper (only caller is `__main__`), U3.
- [ ] T009 [US1] In `src/gh_address_cr/__main__.py`, set `process.executable.name` (basename of `sys.argv[0]` or `"gh-address-cr"`), `process.pid` (`os.getpid()`), and `process.command_args` from the **argv the CLI actually processed** — `safe_command_args([sys.argv[0]] + (argv if argv is not None else sys.argv[1:]))` — so tests that call `main([...])` get a deterministic value instead of the test runner's `sys.argv` (U1).

**Checkpoint**: US1 fully functional and independently testable (MVP core).

---

## Phase 4: User Story 2 — Correlate a CLI run back to the agent (Priority: P2)

**Goal**: When a caller injects a well-formed `TRACEPARENT`, the span nests under
that trace (dormant path, G-1); otherwise it records `process.parent_pid` as a
breadcrumb and runs as a root span. Fail-open on all context inputs.

**Independent Test**: Run with a well-formed `TRACEPARENT` env, with a malformed
one, and with none; assert parent linkage, root fallback, and `process.parent_pid`
presence — exit code unchanged in every case.

### Tests for User Story 2 (write first, ensure they FAIL)

- [ ] T010 [P] [US2] In `tests/test_cli_otel_context.py`, add a test that a well-formed `TRACEPARENT` env makes the span a child of the injected trace/span id (in-memory exporter).
- [ ] T011 [P] [US2] In `tests/test_cli_otel_context.py`, add a test that a malformed and an absent `TRACEPARENT` both yield a root span with the CLI exit code unchanged (fail-open, FR-005/C-8).
- [ ] T012 [P] [US2] In `tests/test_cli_otel_context.py`, add a test that `process.parent_pid` equals `os.getppid()` and does not alter the span's trace id.

### Implementation for User Story 2

- [ ] T013 [US2] Add `resolve_parent_context(environ) -> Context | None` to `src/gh_address_cr/telemetry.py` using `TraceContextTextMapPropagator().extract({"traceparent": value})`; return `None` when absent, and rely on extract's INVALID-context behavior for malformed values (no exception path).
- [ ] T014 [US2] Extend `run_traced` in `src/gh_address_cr/telemetry.py` to accept an optional `parent_context` and pass it to `start_as_current_span(..., context=parent_context)`; behavior unchanged when `None`.
- [ ] T015 [US2] In `src/gh_address_cr/__main__.py`, call `resolve_parent_context(os.environ)`, pass the result to `run_traced`, and set `process.parent_pid` from `os.getppid()` — if `getppid` is unavailable/raises (non-POSIX edge), omit the attribute rather than fail the span (U2, fail-open); add an inline comment documenting the `TRACEPARENT` path as dormant (see research.md R-002).

**Checkpoint**: US1 + US2 both independently functional.

---

## Phase 5: User Story 3 — CLI tool calls in the AI tool-call view (Priority: P3)

**Goal**: The same span reports `gen_ai.operation.name=execute_tool`,
`gen_ai.tool.name`, and `gen_ai.tool.call.arguments` (reusing US1's sanitized
argv). `gen_ai.tool.call.result` is intentionally omitted (G-3).

**Independent Test**: Invoke the CLI under an in-memory exporter; assert the three
GenAI attributes are present, `tool.call.arguments` equals the sanitized argv
(minus system-only flags), and `tool.call.result` is absent.

### Tests for User Story 3 (write first, ensure they FAIL)

- [ ] T016 [P] [US3] In `tests/test_cli_otel_genai.py`, add a test that the span has `gen_ai.operation.name == "execute_tool"`, a present `gen_ai.tool.name`, and NO `gen_ai.tool.call.result` attribute.
- [ ] T017 [P] [US3] In `tests/test_cli_otel_genai.py`, add a test asserting `json.loads(span.attributes["gen_ai.tool.call.arguments"]) == list(span.attributes["process.command_args"])` — i.e. the JSON-string arguments decode to exactly the same sanitized argv, no independently-filtered copy (A1). (Note: the FR-007 "exclude system-only flags" clause is **vacuous in v1** since no system-only flags exist until G-2.)

### Implementation for User Story 3

- [ ] T018 [US3] Add a `derive_tool_name(argv) -> str` helper (parse the top-level command token, fallback `"gh-address-cr"`) to `src/gh_address_cr/core/telemetry_safety.py`.
- [ ] T019 [US3] In `src/gh_address_cr/__main__.py`, set `gen_ai.operation.name = "execute_tool"`, `gen_ai.tool.name` (via `derive_tool_name`), and `gen_ai.tool.call.arguments` (JSON string of the shared sanitized argv); do NOT set `gen_ai.tool.call.result`.

**Checkpoint**: All three stories independently functional.

---

## Phase 6: Polish & Cross-Cutting

- [ ] T020 [P] Update `specs/026-cli-otel-agent-integration/quickstart.md` cross-checks if any attribute name/behavior drifted during implementation; ensure the dormant `TRACEPARENT` note and deferred G-2/G-3 remain accurate.
- [ ] T021 Run `ruff check src tests` and fix any lint from the new modules/tests.
- [ ] T022 Run `python3 -m unittest discover -s tests` and confirm the full suite (including the new files and the pin test) passes.
- [ ] T023 Run CLI smoke checks: `python3 -m gh_address_cr --help` (no new required flags, SC-005) and `DISABLE_TELEMETRY=1 python3 -m gh_address_cr version` (opt-out path unaffected, C-8).
- [ ] T024 Privacy validation: assert across a sampled sensitive-input run that no span attribute (`process.command_args`, `gen_ai.tool.call.arguments`, `error.type`) contains a raw token/credential/username/unnecessary-abs-path (SC-004).

---

## Dependencies & Execution Order

### Phase dependencies
- Setup (P1) → Foundational (P2) → Stories (P3–P5) → Polish (P6).
- Foundational (T002–T003) blocks all stories (constants used everywhere).

### Story dependencies
- **US1 (P1)**: after Foundational. No dependency on US2/US3. **MVP.**
- **US2 (P2)**: after Foundational. Independent of US1/US3, but T014 edits the same `run_traced` as US1's T008 → run US1 before US2 to avoid same-file churn.
- **US3 (P3)**: after Foundational. Reuses US1's `safe_command_args` (T007) for `tool.call.arguments` → US1 before US3.

### Within each story
- Tests (fail first) → implementation.
- `safe_command_args` (T007) before it is reused in T019.

### Shared-file serialization (NOT parallel across stories)
- `src/gh_address_cr/telemetry.py`: T008 (US1), T013/T014 (US2).
- `src/gh_address_cr/__main__.py`: T009 (US1), T015 (US2), T019 (US3).
Do these in story-priority order; only the `[P]` test files and T002/T003/T018 (distinct files) parallelize.

---

## Parallel Example: User Story 1

```bash
# Tests (distinct files) in parallel:
Task: "T004 success-span attributes test in tests/test_cli_otel_execution.py"
Task: "T006 safe_command_args redaction tests in tests/test_telemetry_safety_command_args.py"
```

---

## Implementation Strategy

### MVP First (US1 only)
1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **STOP & VALIDATE**
   (US1 alone delivers the forensic "what did the agent send + what happened"
   evidence, the core value). Ship if ready.

### Incremental Delivery
US1 (forensics) → US2 (dormant context linking + parent_pid) → US3 (GenAI tool
vocabulary). Each adds value without breaking prior stories. G-2/G-3 remain
deferred to a follow-up architecture spec.

---

## Notes
- Every span attribute uses the `otel_semconv` constants (G-4), never string literals.
- `process.command_args` and `gen_ai.tool.call.arguments` MUST share one `safe_command_args` result (FR-002/FR-007).
- Telemetry stays fail-open: no task may let a telemetry failure change the CLI exit code (C-8), except none here does (G-2 fail-loud flag is out of scope).
- Commit after each task or logical group; do not stage/commit without explicit request.
