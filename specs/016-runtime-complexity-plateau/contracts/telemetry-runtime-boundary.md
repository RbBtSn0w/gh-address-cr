# Contract: Telemetry Runtime Boundary

## Purpose

Keep telemetry useful for workflow evidence and optimization without making it completion authority or a performance bottleneck.

## Coverage Summary Shape

```json
{
  "coverage_label": "runtime-only",
  "sources": ["runtime"],
  "write_status": "available",
  "diagnostics": [],
  "privacy_status": "safe",
  "report_path": "efficiency_report.json",
  "overhead_ms": 42
}
```

## Required Behavior

- Core review-resolution flows fail open when telemetry is missing, damaged, slow, or unavailable.
- Telemetry-specific commands fail loudly for malformed, unsafe, unsupported, or ambiguous telemetry.
- Normal telemetry work should add no more than 250ms user-visible delay per core workflow command.
- When telemetry exceeds the budget or cannot write safely, runtime emits a coverage diagnostic instead of blocking core review completion.
- The in-memory report returned to final-gate/summary commands owns the final measured overhead; the persisted JSON artifact is a single-write snapshot and may leave final overhead unset rather than performing an unmeasured rewrite.
- Public reports must preserve source attribution and never expose tokens, credentials, raw prompts, usernames, private machine identifiers, or unnecessary absolute local paths.
- Telemetry never mutates review item state and never replaces reply, resolve, evidence, or final-gate truth.

## Coverage Labels

- `complete`: Runtime and expected external sources were available and safe.
- `partial`: Some expected telemetry sources were missing, rejected, or degraded.
- `runtime-only`: Runtime telemetry exists but external/host telemetry is absent.
- `unavailable`: Telemetry could not be safely read or reported.
