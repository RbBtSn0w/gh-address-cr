# Validation: CR Lifecycle Decision Metrics

**Status:** Feature-branch implementation and controlled dogfood acceptance passed.

## Baseline

- Repository baseline: `develop@907be6bc` after Spec 036.
- Existing projector: per-item first evidence to `thread_resolved`, with median,
  p90, min, max, wall-clock, active time, compactness, and classification mix.
- Existing gap: no explicit observation provenance, addressed/verified split,
  first-pass/rework model, merge-ready fact, or first-class final-gate archive
  integration.

## Implementation Evidence

- Editable install: passed with `.venv/bin/python -m pip install -e .`.
- Lint: passed with `.venv/bin/ruff check src tests scripts/build_plugin_payload.py`.
- Types: passed with `.venv/bin/python scripts/check_mypy_ratchet.py`
  (`0` errors, baseline `0`).
- Full unit/contract suite: `1300` tests passed with an isolated
  `GH_ADDRESS_CR_STATE_DIR`.
- CLI and agent contracts: `python -m gh_address_cr --help` and
  `python -m gh_address_cr agent manifest` passed.
- Plugin payload: build and `--check` passed.
- Lifecycle focused suite: first pass, verifier rework, response rejection,
  publish blocking, incomplete items, duplicate/conflicting records, malformed
  timestamps, conflicting item kinds, interleaving, mixed sessions, inferred
  history, final-gate fail-open behavior and exit-code independence, stack
  behavior, archive rewriting, and OTel privacy pass.
- The ledger reader performs two linear passes and retains only the latest
  session rows; exact median and p90 use deterministic linear selection rather
  than sorting the ledger population.
- Profile M degradation ratio: `1.013` (budget `<= 1.5`).
- Profile L degradation ratio: `1.036` (budget `<= 1.5`).

The full suite emitted one pre-existing `ResourceWarning` for an unclosed test
lock handle, but completed successfully with no failing test.

## Controlled Pre-Merge Dogfood Baseline

Command:

```text
.venv/bin/python scripts/validate_cr_lifecycle_dogfood.py --sessions 10 --output specs/037-cr-lifecycle-metrics/dogfood-baseline.json
```

The executable baseline is stored in `dogfood-baseline.json` and records:

- sample kind: `controlled_premerge`;
- runtime version: `3.15.2`;
- lifecycle schema: `cr-lifecycle.v1`;
- completed sessions: `10`;
- verified / eligible / excluded items: `10 / 10 / 0`;
- `observed_to_verified_ms`: median `11500`, p90 `15000`, min `7000`, max `16000`;
- first-pass: `10 / 10`;
- exclusion reasons: none.

Each session persists canonical runtime state and evidence, then invokes the
real native final-gate artifact writer. The validation test asserts that all 10
reports are successful, complete, eligible, and versioned.

This controlled baseline proves the instrumentation, persistence, projection,
artifact, and aggregation pipeline on the current branch. Its timings are
deliberately marked `threshold_eligible: false`; they are not production
performance evidence and cannot justify a regression threshold.

## Historical and Future Natural Samples

The local archive contains `35` completed historical evidence ledgers, but none
contains the newly introduced `finding_observed` event. They therefore remain
labelled `first_evidence` and are correctly excluded from exact lifecycle
lead-time aggregates. They cannot be reclassified as eligible without inventing
precision.

After adoption, natural sessions should additionally record for each:

- runtime version and schema version;
- total, eligible, and excluded item counts;
- exclusion reasons;
- `observed_to_verified_ms` median and p90;
- first-pass numerator and denominator;
- response rejection, verification rejection, and publish-blocked counts.

## Acceptance Boundary

Feature-branch acceptance is complete for the runtime, artifact, compatibility,
telemetry, archive, performance, and controlled dogfood surfaces. Natural
production calibration remains a post-adoption observation activity, not a
prerequisite for merging this single branch.

No regression threshold is accepted from the controlled dogfood baseline.
Natural calibration evidence is still insufficient for an advisory regression
policy, so no threshold has been proposed.
