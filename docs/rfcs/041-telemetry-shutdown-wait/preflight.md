# Spec 041: Bounded exit-time telemetry wait (issue #346)

Architecture Preflight for a change that touches the telemetry reporting
contract (`telemetry_overhead_ms`). Current code, tests, and `AGENTS.md` govern
execution.

## Problem (verified)

`shutdown_telemetry()` joined the provider shutdown for up to 2.2 s, so every
CLI invocation (including `--help`) paid the OTLP round trip before exiting, and
neither the root span nor `telemetry_overhead_ms` could see it. Reproduction with
an endpoint that accepts connections and never answers, `--help`, median of 5:
2.35 s before, 0.30 s with `DISABLE_TELEMETRY=1`.

## Preflight

| Item | Decision |
| --- | --- |
| Authoritative state owner | None new. Review state stays in `runtime.sqlite3`. The wait is observed evidence, not state. |
| External facts / inputs | The wall-clock duration of the exit-time provider shutdown, measured by `shutdown_telemetry`, and whether the join timed out. |
| Projection | `telemetry-shutdown-wait.json` in the state dir holds only the latest `{wait_ms, timed_out, recorded_at}`. It is a derived observation, written last-writer-wins by `write_json_atomic`, never read by `final-gate`, never authoritative. |
| Policy | `SHUTDOWN_JOIN_TIMEOUT_SECONDS = 0.3`. An export still in flight at the bound is abandoned with its daemon thread. Fixed constant, no branching. |
| Side-effect plan | No new network IO. One small local file write per invocation, best effort. |
| Artifact truth boundary | `efficiency-report.json` gains `telemetry_shutdown_wait_ms` (the previous invocation's recorded wait, or `null`). `telemetry_overhead_ms` = report build time + that wait, checked against the existing 250 ms budget. |
| Self-reference risk | An invocation cannot include its own exit wait: it happens after the report is sealed. Excluded boundary: the current invocation's own shutdown wait is excluded; the preceding invocation's wait is included. The current wait is separately bounded by the contract test. |
| Recovery / replay | A missing, malformed, or unwritable record yields `null` and no diagnostic. Core flows stay fail-open. |

## Alternatives rejected

- **Detached helper / local spool.** Preserves delivery on slow links, but adds a
  second process lifecycle, a spool store with ordering/retention/privacy rules,
  and a delivery path that outlives the CLI. That is a new subsystem beyond the
  protected baseline (principle X) for a problem a fixed bound already removes.
  Revisit with delivery-loss evidence from the gateway.
- **Wall-clock root span attribute.** Same self-reference problem for the span
  that is still open, and it would not reach the efficiency report.

## Accepted trade-off

Exports slower than 0.3 s after the command finishes are dropped. On a link with
a ~1.2 s round trip most root spans are lost until a spool exists. `timed_out`
makes the rate observable locally.

## Executable contract tests

- `tests/test_otel_telemetry.py`: shutdown against an unresponsive endpoint
  returns within the documented bound and records the wait; the bound stays
  under 0.5 s.
- `tests/core/test_telemetry.py`: the previous recorded wait is included in
  `telemetry_overhead_ms`, can trigger `TELEMETRY_OVERHEAD_EXCEEDED`, and a
  missing or malformed record is ignored.
