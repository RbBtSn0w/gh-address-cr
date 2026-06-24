# Architecture Spec: `core/telemetry` God-Module Decomposition (#153)

Status: in progress. This is the Architecture Preflight artifact mandated by
`AGENTS.md` for the telemetry subsystem, which is the highest-churn area of the
codebase. It supersedes the decomposition scope of the earlier
`spec.md` (which bundled #152 type-safety and #154 exception work) and defines
the authoritative module seams so future `fix(telemetry):` changes land in a
cohesive sub-module instead of re-expanding the god module.

## 1. Problem

`core/telemetry.py` was a 1,839-line god module concentrating four distinct
responsibilities: shared data types, the stateful runtime tracker, the
ingest/normalize/persist pipeline, and efficiency reporting. High churn and
repeated reactive `fix(telemetry):` commits confirmed the structural risk.

## 2. Target sub-modules and dependency direction

Dependencies point **downward only**; there are no cycles.

```
                 telemetry_safety   (leaf: redaction / content-safety helpers)
                          ^
                          |
   telemetry_models  -----+         (leaf: dataclasses, TypedDicts, thresholds)
        ^      ^
        |      |
        |   telemetry_reporting      (pure derivation + markdown + CLI health)
        |      ^
        |      |
   telemetry.py  ------------------> host_telemetry/  (auto-capture, text out)
   (runtime tracker + ingest/persist pipeline; orchestrates reporting)
```

| Module | Responsibility | Depends on |
| --- | --- | --- |
| `telemetry_models.py` | `ExecutionMetric`, `EfficiencyReport`, `ExternalTelemetryEvent`, `TelemetryParseResult`; `SlowestOperation`/`EfficiencyReportPayload` TypedDicts; `SAFE_STATUSES`/`SAFE_KINDS`; `MAX_DURATION_SECONDS`/`MAX_ERROR_RATE_PERCENT`. | stdlib only |
| `telemetry_safety.py` | Content-safety / redaction helpers (`_safe_*`, `_contains_*`, `_json_loads_strict`). | stdlib only |
| `telemetry_reporting.py` | Pure report derivation (`_coverage_label`, `_source_rows`, `_error_prone_operations`, `_inefficiency_flags`, `_confidence_for_coverage`, `_aggregate_host_metrics`), CLI health (`_cli_health_issues`, `_last_machine_summary_health_issue`, `_safe_os_error_diagnostic`), and `efficiency_report_markdown`. Operates on already-loaded events + `SessionPaths`; performs no event persistence and never touches `SessionTelemetry`. | models, safety, `core.paths` |
| `telemetry.py` | Stateful `SessionTelemetry` tracker, adapter registry, ingest/normalize/redact/fingerprint/persist pipeline, and `build_efficiency_report` (loads + dedupes events, delegates computation/formatting to `telemetry_reporting`). | models, safety, reporting, `core.paths`, `host_telemetry` |
| `host_telemetry/` | Native host session log -> `agent-jsonl` text; feeds `import_external_telemetry`. Never touches the ingest pipeline directly. | models, `core.paths` |

## 3. Authoritative state & serialization shapes

- **Runtime state** is owned solely by `SessionTelemetry` (a process-singleton
  appending `ExecutionMetric` rows to `telemetry.jsonl`). No other module mutates
  it; reporting reads a fresh tracker view via `_runtime_events`.
- **External events** are persisted as `ExternalTelemetryEvent.to_dict()` JSONL
  plus a fingerprint set, both under `SessionPaths`. `telemetry_models` is the
  single source of truth for these shapes.
- **Efficiency report** is the `EfficiencyReportPayload` TypedDict, written
  atomically to `paths.efficiency_report_file`. Telemetry is observed output and
  must never mutate review-state transitions (Principle I); ingestion stays
  fail-open (Principle VIII).

## 4. Compatibility policy (no shim)

Per `AGENTS.md`, no `# noqa: F401` re-export shim. When a symbol moves modules,
its callers (source **and** tests) are migrated to the real module path in the
same change. `telemetry.py` may import a moved symbol only when it genuinely
uses it internally; symbols used only by external callers (e.g.
`efficiency_report_markdown`) are imported directly by those callers.

## 5. Extraction order & status

1. **#156 — this spec.** Done.
2. **Models seam — `telemetry_models.py`.** Done: shared dataclasses/TypedDicts/
   thresholds extracted; breaks the `telemetry` <-> `telemetry_reporting` cycle.
3. **#158 — `telemetry_reporting.py`.** Done: reporting derivation, CLI health,
   and markdown extracted (~470 lines); `build_efficiency_report` retained in
   `telemetry.py` as the loader/orchestrator and delegates downward. External and
   test callers of `efficiency_report_markdown` migrated to the new module.
4. **#157 — `host_telemetry/`.** Largely complete (profile/capture/attribution/
   strategies/discovery already extracted); remaining adapter-side host parsing
   (`CodexHostJsonAdapter`, `_codex_turn_metadata`, host coercers) is ingest-layer
   and stays in `telemetry.py` with the rest of the pipeline.
5. **#159 — re-export shim removal.** The original 26-name `telemetry_safety`
   shim is gone: all 14 currently-imported safety helpers are used internally by
   `telemetry.py`, and no source/test imports a safety symbol via the
   `telemetry.*` path.

## 6. Verification

- `python3 scripts/check_mypy_ratchet.py` — baseline 0 errors (strict flags).
- `python3 -m unittest discover -s tests` — full suite (no behavior change).
- `ruff check src tests` — including import-order and unused-import (F401) gates,
  which enforce the no-shim policy.
