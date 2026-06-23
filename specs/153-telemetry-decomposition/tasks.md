# Implementation Tasks: Telemetry Decomposition

## Phase 1: Infrastructure & Specs
- [x] Create decomposition spec (`spec.md`)
- [x] Create data model spec (`data-model.md`)
- [ ] Review spec with maintainer (simulated via self-correction)

## Phase 2: Code Extraction
- [ ] Create `telemetry_reporting.py` and move reporting classes/functions.
- [ ] Create `telemetry_attribution.py` and move fingerprinting/deduplication logic.
- [ ] Create `telemetry_import.py` and move adapter and import logic.
- [ ] Clean up `telemetry.py` and remove the re-export shim.

## Phase 3: Integration & Migration
- [ ] Update internal imports in `final_gate.py`.
- [ ] Update internal imports in `telemetry_health.py`.
- [ ] Update internal imports in all other `core/` modules.

## Phase 4: Verification
- [ ] Update tests to point to new modules.
- [ ] Run `ruff check` to ensure no linting regressions.
- [ ] Run `python3 -m unittest discover -s tests` to verify behavior.
- [ ] Run CLI smoke tests (`final-gate`, `telemetry summary`).
