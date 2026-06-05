# Contract: Telemetry And Reporting Boundary

## Scope

This contract defines how telemetry and reporting interact with the runtime-kernel slice.

## Boundary Rules

- Telemetry and reporting facts may record diagnostics, coverage, confidence, and overhead.
- Telemetry and reporting facts must not mark review-thread work complete.
- Reporting artifact writes must not create recursive completion requirements.
- When exact overhead would require including the reporting write itself, the reporting write is excluded from the measured runtime-kernel completion boundary.

## Accepted Diagnostic Fact

`reporting_observed` facts may include:

- `coverage_label`
- `diagnostics`
- `overhead_ms`
- `report_path`
- `write_status`

These fields are diagnostic only.

## Prohibited Semantics

- A report path alone must not satisfy reply evidence.
- A telemetry coverage label alone must not satisfy final-gate eligibility.
- A reporting write failure must not create new review work unless a separate feature explicitly models reporting as a versioned event source with tests.

## Verification Requirements

Tests must prove that adding reporting-only facts does not change review work completion or create recursive blockers.
