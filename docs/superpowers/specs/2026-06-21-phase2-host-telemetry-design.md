# Phase 2 — Host Telemetry via Native-Log Profiles (Design Spec)

**Status:** Design / awaiting review
**Date:** 2026-06-21
**Predecessor:** Phase 0+1 (honest timing reporting + validation timing suffix) — implemented on branch `feat/telemetry-timing-honest-reporting`.

## 1. Goal & Context

Phase 0/1 made telemetry *trustworthy* for the validation slice of a session: durations are real when reported, and absence is labeled honestly (`TELEMETRY_TIMING_UNAVAILABLE`) instead of shown as misleading `0ms`. But whole-session performance perception still does not happen automatically, because:

- Runtime telemetry only records commands the runtime itself executes or that the agent reports back as validation evidence. The bulk of an agent-driven session (exploration, edits, tool calls, waits) is never captured.
- The host-telemetry ingestion hook (`GH_ADDRESS_CR_HOST_TELEMETRY_INPUT`) already exists, but nobody produces the file or sets the variable, so it is empty in practice.

**Phase 2 goal:** automatically capture whole-session performance/problem signals by *reading the host's own native session log*, mapping it into the existing normalized telemetry schema, with no per-session manual setup. First-party support: Claude Code and Codex. The mechanism is generalized so additional hosts are added by writing a declarative profile, not new final-gate branches.

### Capability survey evidence (decisive)

From a real Claude Code transcript (`~/.claude/projects/<slug>/<session>.jsonl`):

- Per-entry `timestamp` present on 660/869 entries.
- `tool_use` blocks carry `name` (→operation) and `id`; `tool_result` blocks carry `tool_use_id` (→correlation) and `is_error` (→status).
- **No native per-tool `durationMs`** — duration must be *derived* by pairing `tool_use`→`tool_result` timestamps.
- Pairing yields **458/458 tool events paired (100%)**, status mix 445 success / 13 failure, full slowest-operation ranking and total observed duration.
- **Semantic caveat:** the slowest "operations" are interactive (`ExitPlanMode` 892s, `AskUserQuestion` 742s) — these measure *human wait time*, not agent compute. They must be classified as `kind: wait`, not `tool_call`, so they do not pollute agent-performance perception.

Conclusion: the pull-from-native-log direction is **feasible for the dominant host**, and the existing schema already accommodates it.

## 2. Design Center & Non-Goals

Phase 2 deliberately diverges from mainstream LLM-observability stacks (Langfuse / OpenInference / Arize / Jaeger). Those assume *capture as much input/output/prompt/token as possible and export to a SaaS backend*. This project's design center is the opposite, on three hard lines:

1. **Privacy-first, allowlist extraction.** Prompts, tool inputs, tool outputs, and tokens are blocked by `UNSAFE_METADATA_KEYS` + redaction. Extraction emits only named-safe fields; it never reads `tool_use.input` or `tool_result.content`.
2. **Deterministic gate > LLM judge.** Task success is decided by `final-gate`'s deterministic assertions (thread resolved, reply evidence persisted), because this domain has ground truth. Telemetry measures *efficiency*, never *correctness*, and has no authority over review state.
3. **Local, PR-scoped, zero egress.** No telemetry leaves the machine. No SaaS backend.

### Explicit Non-Goals (固化为设计约束，防止未来漂移)

These are rejected by design — do not add them in Phase 2 or later without revisiting the three lines above:

- **LLM-as-a-Judge correctness/hallucination scoring** — conflicts with line 2 (deterministic gate owns correctness).
- **Capturing tool input arguments or output content** — conflicts with line 1 (allowlist).
- **Exporting spans to a third-party SaaS backend (Langfuse/Arize/Jaeger)** — conflicts with line 3 (zero egress).
- **"Hallucination backlash" detection (tool-output ignored)** — requires both input/output capture and an LLM judge; conflicts with lines 1 and 2.

What we *do* borrow from OpenTelemetry: the span data model, the semantic-convention field mapping (for interop), and the aggregation ideas for problem discovery. Not the full-capture, SaaS-export, or LLM-judge machinery.

## 3. Architecture

A new **host-profile adapter layer** sits in front of the *existing* ingestion pipeline. Nothing downstream is rewritten.

```
host native log ──[mapping profile + strategy]──▶ agent-jsonl events ──▶ existing ingest pipeline ──▶ efficiency report
  (CC transcript)      declarative extraction          (existing schema)    (normalize→safety→
                                                                              fingerprint→dedupe→report)
```

- Discovery + extraction run automatically at `final-gate` (replacing reliance on the manual env var; the env var remains as an explicit override).
- All safety, fingerprint, dedupe, coverage-label, and fail-open contracts are reused unchanged.

### Component boundaries

| Unit | Responsibility | Depends on |
|---|---|---|
| `profile_registry` | Load + resolve host profiles (JSON) by detection | profile JSON files |
| `extraction_strategies` | Named code-level primitives that turn a parsed log into events | profile field paths |
| `host_discovery` | Locate the active host log + resolve the current session | profile `discovery` block |
| `scope_attribution` | Filter extracted events to the active PR by time-window + session id | PR session state |
| existing ingest pipeline | normalize / redact / fingerprint / dedupe / report | (unchanged) |

## 4. Mapping Profile Schema

A profile is declarative JSON. It *selects* a named extraction strategy and supplies field paths. Honest boundary: a purely declarative profile cannot express cross-record correlation joins (e.g., pair `tool_use`↔`tool_result` by id and diff timestamps). So the mechanism is **hybrid**: a small set of code-level **extraction strategies** are the primitives; profiles choose a strategy by name. A host matching an existing strategy = pure profile (no code); a genuinely new log shape = one new strategy (code).

```json
{
  "profile_version": "1.0",
  "source": "claude-code",
  "format": "claude-code-transcript",
  "discovery": {
    "glob": "~/.claude/projects/{project_slug}/*.jsonl",
    "project_slug_from": "cwd"
  },
  "record": { "container": "jsonl-lines", "session_id_path": "sessionId" },
  "strategy": "paired-correlation-timestamp",
  "fields": {
    "event_blocks_path": "message.content[]",
    "tool_use":   { "match": {"type": "tool_use"},   "id_path": "id", "operation_path": "name" },
    "tool_result":{ "match": {"type": "tool_result"},"correlation_path": "tool_use_id",
                    "status_path": "is_error", "status_map": {"true": "failure", "false": "success"} },
    "timestamp_path": "timestamp"
  },
  "kind_classification": {
    "default": "tool_call",
    "wait": ["AskUserQuestion", "ExitPlanMode"],
    "by_operation": { "Bash": "command" }
  },
  "safety_allowlist": ["operation", "status", "timestamp", "correlation_id", "error_type", "parent_event_id"],
  "scope_attribution": { "mode": "active-pr-time-window" }
}
```

Key rules:

- `safety_allowlist` is a hard whitelist: the extractor emits *only* these fields. `tool_use.input` / `tool_result.content` are physically excluded from the pipeline (redaction is a second backstop, not the first).
- `kind_classification` encodes the survey finding: interactive operations → `wait`, so human think-time does not count as agent performance.
- `scope_attribution.mode` selects the PR-scoping rule (§6).
- `discovery` lets `final-gate` locate the log without an env var.

## 5. Extraction Strategies (named primitives)

Two ship in Phase 2:

- **`paired-correlation-timestamp`** (Claude Code): iterate JSONL lines; index `tool_use` blocks by `id` (operation, start timestamp); index `tool_result` blocks by `correlation_path` (status, end timestamp); join by id; `duration_ms = end - start`; unpaired `tool_use` → event with no duration (Phase 0 reports it honestly). Parent turn (`agent_step`) → child `tool_call` parent-child link populated from the enclosing message uuid where available.
- **`record-pair-timestamp`** (top-level event-record logs such as Codex native sessions): profile-specified start/end records are paired by a profile-specified correlation id path; `duration_ms` is derived from timestamps; emitted fields are limited to operation/status/timing/correlation. Payload arguments, outputs, prompts, and file contents are never emitted.
- **`flat-duration-field`** (Codex aggregate export shape): events carry a direct `duration_ms` (or `started_at`+`ended_at`); no pairing needed. The existing `CodexHostJsonAdapter` remains the public explicit-import adapter for aggregate Codex host exports.

A profile naming a strategy that does not exist → fail-open with a diagnostic (§9), never a crash.

## 6. PR-Scope Attribution

The host log is session-scoped; this project is PR-scoped. A Claude Code session may touch multiple PRs or none.

**Rule (`active-pr-time-window`):** the attribution window = `[PR session created_at, final-gate time]` (the PR session's `created_at` already exists in session state). A log event is attributed to this PR iff: (1) it belongs to the current host `sessionId`, **and** (2) its `timestamp` falls within the window. Cross-PR and historical events are excluded by construction.

- If multiple distinct host session ids fall in the window → `AMBIGUOUS_TELEMETRY_SESSION` (existing reason code) + fail-open.

## 7. Auto-Discovery & Default Posture

**Host detection:** a host is detected by trying each registered profile's `discovery` block against the current `cwd`; the host is the profile whose glob resolves to an existing transcript that contains an active session within the attribution window (§6). Zero matches → fail-open (no host telemetry). More than one host profile matching is not expected on a single machine; if it occurs, prefer the profile with the most recently modified log and record a diagnostic.

**Flow at `final-gate`:** detect host → resolve profile → glob to locate transcript → select the active session → extract events within the attribution window → feed the existing ingest pipeline → write the efficiency report. Any failed step → fail-open to current behavior (`runtime-only`/`unavailable`).

**Default posture: on by default, opt-out via env.** This directly answers the original problem ("nobody sets the env var, so it is always empty"). What makes default-on safe is the two gates already designed: allowlist extraction (no content/prompt/token enters the pipeline) and time-window+session scoping (only the current PR's work is read, never history).

**First-run consent notice (R1).** Default-on means the very first auto-discovery reads the user's local transcript without prior explicit consent — surprising in shared or enterprise environments even though only allowlisted fields are extracted. Therefore: on the **first** auto-discovery for a given host on this machine, print a one-time stderr notice and persist a consent marker in the state dir:

```
gh-address-cr: detected <host> session transcript; reading operation/status/timing only
(no prompts, file contents, or tokens) for efficiency telemetry. Opt out:
GH_ADDRESS_CR_HOST_TELEMETRY_AUTO=0. This notice is shown once.
```

Subsequent runs do not repeat the notice (marker present). This turns implicit consent into an explicit, auditable one-time acknowledgement without re-introducing per-session setup friction.

**Audit transparency:** when the report labels `coverage_label: complete`, it annotates the source as `claude-code (auto-discovered)`, so "the runtime read your local transcript" is visible and explainable, never silent.

- Opt-out: `GH_ADDRESS_CR_HOST_TELEMETRY_AUTO=0` disables auto-discovery.
- Explicit override: `GH_ADDRESS_CR_HOST_TELEMETRY_INPUT` (existing) still forces a specific feed.

## 8. Schema Additions (OTel-borrowed, additive, in-bounds)

All additions are **optional fields populated per-profile from allowlisted data only**, and route through safe metadata. None rename existing fields (see §10).

- **`error_type?`** — coarse error classification (`timeout` / `auth` / `http_4xx` / `http_5xx` / `exception`) derived from allowlisted discrete fields (e.g., Bash `exit_code`, a discrete HTTP status). Expectation is explicitly low-resolution for Claude Code: it can surface "this tool fails often," it **cannot** surface "an int was passed as a string" (that needs input content, which is forbidden).
- **`parent_event_id?`** — explicit parent-child link (`agent_step` turn → child `tool_call`). Evidence: Claude Code tool_use blocks nest under an assistant turn with `requestId`/`uuid`; the Codex adapter already populates an equivalent link. Populated where the profile can derive it cheaply.

## 9. Report Additions & Safety / Fail-Open

### New inefficiency signal: fingerprint-repeat-frequency

Existing loop detection counts consecutive retries. Add a signal that counts **repeated event fingerprints** (full fingerprint, which already includes operation+status+duration) within the attribution window, flagging suspected loops. Correctness note: counting bare `operation` repeats would false-positive on legitimate repeated tools (many `Bash` calls); counting **full-fingerprint** or **failed-fingerprint** repeats is the precise signal and needs no input arguments. Uses only existing safe fields — no privacy impact.

### Fail-open / safety table (all reuse existing contracts)

| Situation | Behavior |
|---|---|
| No profile / no transcript / parse failure | fail-open, `runtime-only`, diagnostic `TELEMETRY_HOOK_UNAVAILABLE` |
| Multiple sessions in window | fail-open, `AMBIGUOUS_TELEMETRY_SESSION` |
| Unsafe content slips past allowlist | second backstop: `telemetry_safety` redaction/reject |
| `final-gate` core workflow | never affected by telemetry (fail-soft unchanged) |

## 10. OTel Interop Mapping (documentation only — no rename)

The core schema field names are a stable public contract (spec 015 + acceptance matrix + tests) and are **not** renamed. This table documents the correspondence for future interoperability; an OTel export *view* (aliases) may be added later without touching the source.

| OTel semantic convention | gh-address-cr field |
|---|---|
| `trace_id` | `source_session_id` (+ PR scope) |
| `span_id` | `event_id` |
| `parent_span_id` | `parent_event_id?` (new, §8) |
| `tool.name` | `operation` |
| `tool.status_code` | `status` |
| `tool.error.type` | `error_type?` (new, §8) |
| `duration_ms` | `duration_ms` |
| `tool.type` | `kind` (richer here — includes `wait`) |

## 11. Agent-Self-Authoring Profile Path (推广路径)

Because a profile is declarative JSON over a documented set of strategies, the profile format + strategy catalog (each strategy's required field paths) is published as an authoring guide. To onboard a new host, the guide can be handed to an agent running under that host (e.g., a Codex agent): it reads its own native log shape, matches a strategy, and emits a profile JSON — no code change, provided the host fits an existing strategy. A host with a genuinely novel log shape requires one new strategy (code) plus the profile. This is the stepwise rollout path: Claude Code first-party now; others as profiles contributed over time.

## 12. Testing Strategy & Verifiable Evidence

Tests use `unittest` (`PYTHONPATH=src python -m unittest <module>`). Layered to risk:

- **Strategy unit tests** (`tests/core/`): feed a fixture transcript through `paired-correlation-timestamp`; assert paired count, derived durations, status mapping, `wait` classification for interactive ops, unpaired-event handling. Fixture is a small synthetic JSONL checked into `tests/fixtures/telemetry/`.
- **Profile resolution tests:** profile loads, strategy resolves, unknown-strategy → fail-open diagnostic.
- **Scope attribution tests:** events inside/outside the time-window; wrong session id excluded; multi-session → `AMBIGUOUS_TELEMETRY_SESSION`.
- **Safety tests:** assert `tool_use.input` / `tool_result.content` never appear in emitted events or artifacts even when present in the fixture; token-bearing fixture is rejected/redacted.
- **End-to-end:** synthetic CC transcript fixture → auto-discovery (mocked glob/cwd) → ingest → `build_efficiency_report` → assert real durations, `wait` excluded from agent-performance flags, `coverage_label: complete` with `auto-discovered` annotation.
- **Acceptance matrix:** add new rows under existing categories (`host-hook`, `statistics`, `coverage`) in `specs/015-external-agent-telemetry/acceptance-matrix.md`, each citing a new executable test (the meta-test `test_telemetry_acceptance_matrix.py` enforces this).
- **Fail-open regression:** missing transcript, corrupt line, ambiguous session — assert `final-gate` still completes with the right coverage label and never raises.

**Verifiable acceptance:** a synthetic-transcript end-to-end test produces a non-zero, `wait`-excluded slowest-operation set and `complete` coverage; the real-transcript survey numbers (458/458 paired) are reproducible via the same strategy on a real log during manual smoke.

## 13. Known Risks & Limitations (explicit, not hidden)

- **R2 — Time-window attribution is coarse.** If one host session works PR-A then PR-B and `final-gate` runs on PR-B, the window `[PR-B created_at, now]` can include same-session PR-A tail events (the session-id filter cannot separate them — same session). This design **accepts** the coarseness and labels it as *session-near-PR efficiency*, not exact per-PR isolation. A future refinement may add a `cwd`/repo-reference filter; out of scope here.
- **R3 — Coupling to Claude Code's undocumented transcript format.** A field rename is absorbed by editing the profile; but a *strategy-level* change (e.g., the host stops correlating by `tool_use_id`) breaks `paired-correlation-timestamp`. Mitigation: the profile carries a format health self-check (e.g., expected pairing ratio threshold); on degradation it emits an explicit `TELEMETRY_HOOK_UNAVAILABLE` diagnostic rather than silently reporting `unavailable`, so the breakage is visible. Fail-open still guarantees `final-gate` never crashes.
- **R5 — §11 agent-self-authoring is aspirational, not guaranteed.** Handing the profile spec to an agent can produce a wrong field path → silent under-capture. Mitigation: ship a **profile validator / dry-run** that reports "extracted N events, M dropped, pairing ratio X%" against a sample log, so an authored profile is verified before trust. Until that validator exists, self-authored profiles are unverified.

## 14. Implementation Decomposition (R4 — two plans, not one)

This spec is intentionally split into two independent implementation plans so the verifiable closed loop ships first:

- **Plan A — core whole-session capture (ship first):** profile registry + first-party Claude Code and Codex native profiles + host discovery + PR-scope attribution (§6) + first-run consent notice (§7/R1) + auto-discovery wiring into `final-gate` + the safety/fail-open boundaries (§9) + the format health self-check (R3). Acceptance: synthetic-transcript end-to-end tests yield real, `wait`-excluded durations and complete/partial coverage without leaking prompt, argument, output, or file content.
- **Plan B — OTel-borrowed increments (ship after A):** optional `error_type` / `parent_event_id` fields (§8), the fingerprint-repeat-frequency inefficiency flag (§9), the OTel interop mapping doc (§10), and the profile validator / dry-run (R5). These are additive and independent of Plan A's closed loop.

Each plan produces working, tested software on its own.

## 15. Open Questions / Future

- **token/cost dimension** — host-only; deferred until host telemetry carries it (post-Phase-2).
- **Additional host profiles** (Cursor, others) — contributed as profiles via §11; each needs its own capability survey for field availability.
- **OTel export view** — optional later alias layer (§10), not in this scope.
