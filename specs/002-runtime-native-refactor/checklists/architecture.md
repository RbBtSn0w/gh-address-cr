# Architecture Alignment Checklist: Runtime Native Refactor

**Purpose**: Validate that the requirements correctly define the native package boundaries, performance benchmarks, and alignment with project constitutional principles (specifically Principle VI).
**Created**: 2026-04-24
**Feature**: [specs/002-runtime-native-refactor/spec.md](../spec.md)

## Requirement Completeness & Boundary Definition

- [ ] Are the explicit boundaries between `core`, `github`, and `intake` packages defined to prevent circular dependencies? [Completeness, Spec §Requirements]
- [ ] Does the spec explicitly list which logic from `legacy_scripts` is *excluded* from the native migration? [Completeness, Gap]
- [ ] Are the internal API contracts for `GitHubClient` and `SessionManager` specified with error handling behavior? [Clarity, Contracts]
- [ ] Is the "zero-dependency" requirement on `legacy_scripts` defined with a measurable verification method? [Measurability, Spec §SC-001]

## Constitution Alignment (Principle VI - Lease Policy)

- [ ] Does the spec define how the native `core.workflow` implements the claim lease metadata (expiry, owner) in the session state? [Completeness, Plan §Constitution Check]
- [ ] Are the requirements for lease conflict detection (e.g., when two agents claim the same item) explicitly documented? [Coverage, Principle VI]
- [ ] Is the state transition logic in `workflow.py` aligned with the "Lease-First" mutation principle? [Consistency, Principle VI]

## Performance & Metric Quantification

- [ ] Is the "package size stability" (SC-003) quantified with a specific baseline or percentage threshold? [Clarity, Spec §SC-003]
- [ ] Does the spec define the specific environment and data set for the performance benchmarking (SC-004)? [Clarity, Spec §SC-004]
- [ ] Are the "execution time" metrics defined for both success and failure paths in the benchmarks? [Coverage, SC-004]

## Behavioral Parity & Verification

- [ ] Is "bit-for-bit identical session files" defined as the primary parity metric for Story 1? [Measurability, Spec §User Story 1]
- [ ] Does the spec define the required test coverage percentage for the new native packages? [Completeness, Gap]
- [ ] Are the fallback behaviors for shims in `legacy_scripts` documented for cases where native modules fail? [Edge Case, Gap]

## Summary of Focus Areas
- **Architecture**: Ensuring physical separation and strict package hierarchy.
- **Lease Protocol**: Integrating multi-agent safety into the native workflow.
- **Metrics**: Quantifying size and speed requirements to ensure no regressions.
