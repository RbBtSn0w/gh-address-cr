# Implementation Plan: CLI Health Telemetry

## Technical Context

- Python 3.10+ runtime under `src/gh_address_cr`.
- Existing telemetry storage:
  - `telemetry.jsonl` for runtime command metrics.
  - `external-telemetry.jsonl` for normalized imported host events.
  - `telemetry-imports.jsonl` for import summaries and diagnostics.
  - `efficiency-report.json` for diagnostic report artifacts.
- Existing host profiles live under
  `src/gh_address_cr/core/host_telemetry/profiles/`.

## Design Direction

Create a `telemetry_health` core projection layer that owns CLI health taxonomy
and doctor reports. Keep profile-specific details in JSON profiles and generic
profile loading/discovery code.

Runtime flow:

```text
runtime command metrics + import summaries + host profile facts
-> CLI health projection
-> telemetry doctor report / efficiency report diagnostics
```

`final-gate` remains fail-open for missing telemetry. When autodiscovery is
enabled and no host feed is imported, it appends a fail-open diagnostic import
summary with reason code `TELEMETRY_AUTODISCOVERY_MISS`.

## Acceptance Gates

- `telemetry doctor` reports profile/env/discovery/window/store checks with
  stable reason codes.
- Final-gate runtime-only telemetry includes explicit autodiscovery diagnostics.
- Efficiency reports include `cli_health_issues`.
- No review completion state depends on telemetry health artifacts.

