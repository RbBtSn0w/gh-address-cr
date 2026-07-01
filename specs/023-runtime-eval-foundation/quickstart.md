# Quickstart: Validate The Read-Only Evaluation Plane

This guide describes acceptance commands after implementation. It intentionally separates runtime completion proof from evaluation proof.

## Prerequisites

```bash
/opt/homebrew/bin/pyenv exec python -m pip install -e .
export GH_ADDRESS_CR_STATE_DIR="$(mktemp -d)"
```

Use a test repository/PR or fixture-backed test harness. Live observation requires authenticated `/opt/homebrew/bin/gh` access.

## 1. Produce A Provisional Run Archive

Complete the normal review-thread workflow, including publish and final-gate:

```bash
python3 -m gh_address_cr review owner/repo 123
python3 -m gh_address_cr agent publish owner/repo 123
python3 -m gh_address_cr final-gate --auto-clean --audit-id baseline-run owner/repo 123
```

Expected:

- Existing final-gate counts and exit semantics are unchanged.
- The archived run contains `run-manifest.v1.json` with relative artifact paths and post-rewrite digests.
- Manifest/evaluation capture diagnostics, if any, remain visible but do not change a passing final-gate result.

## 2. Build And Inspect Provisional Evaluation

```bash
python3 -m gh_address_cr evaluation rebuild --repo owner/repo --pr-number 123
python3 -m gh_address_cr evaluation show owner/repo 123 --run-id baseline-run --format json
```

Expected before a later review observation:

- Concerns with complete current-cycle evidence report `provisional_state: verified`.
- The same concerns report `durable_state: unknown` and `DURABLE_OBSERVATION_MISSING`.
- Workflow, timing, token, and outcome coverage are separate.

## 3. Capture A Later Reviewer Observation

After a later GitHub reviewer round exists:

```bash
python3 -m gh_address_cr evaluation observe owner/repo 123 --run-id baseline-run
python3 -m gh_address_cr evaluation rebuild --repo owner/repo --pr-number 123
python3 -m gh_address_cr evaluation show owner/repo 123 --run-id baseline-run --format json
```

Expected:

- A supported later round with no correlated reopen/recurrence yields `durable_state: verified`.
- A correlated reopen or equivalent recurrence yields `durable_state: negative`.
- Re-running `observe` records duplicates without increasing outcome counts.
- Merge, PR closure, or elapsed time without a later reviewer round leaves durable state unknown.

## 4. Validate Insufficient Evidence

```bash
python3 -m gh_address_cr evaluation compare \
  --baseline-version 3.1.10 \
  --candidate-version 3.2.0 \
  --format json
```

Expected when either side has fewer than 10 eligible matched runs or lacks required dimensions:

- Exit code is `0` because the evaluation conclusion is valid.
- `status` is `INSUFFICIENT_EVIDENCE`.
- `evidence_deficits` identifies sample, coverage, correlation, or cohort gaps.
- No positive improvement claim or composite score is emitted.

## 5. Validate Active Wall Time

Use fixture spans `[0, 100]`, `[50, 150]`, and `[200, 250]` milliseconds.

Expected:

- `active_wall_time_ms` is `200`.
- `summed_resource_time_ms` is `250`.
- A duration-only event affects resource time but not active wall time.

## 6. Validate Read-Only And Failure Boundaries

Run projection twice and compare semantic fingerprints:

```bash
python3 -m gh_address_cr evaluation rebuild --repo owner/repo --pr-number 123
python3 -m gh_address_cr evaluation show owner/repo 123 --run-id baseline-run --format json > /tmp/eval-first.json
python3 -m gh_address_cr evaluation rebuild --repo owner/repo --pr-number 123
python3 -m gh_address_cr evaluation show owner/repo 123 --run-id baseline-run --format json > /tmp/eval-second.json
```

Expected:

- Projection fingerprints are identical.
- Evaluation capture and report-generation overhead are reported separately from workflow cost.
- Runtime session, evidence ledger, final-gate result, and GitHub thread state do not change.
- Unsafe or malformed observation/archive fixtures make explicit evaluation commands exit non-zero.
- The same missing optional evidence does not block core review completion.

## 7. Repository Verification

```bash
python3 -m pip install -e .
ruff check src tests scripts/build_plugin_payload.py
python3 scripts/check_mypy_ratchet.py
python3 -m unittest discover -s tests
python3 -m gh_address_cr --help
python3 -m gh_address_cr agent manifest
python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr
python3 scripts/build_plugin_payload.py --check
```

Contract-focused tests must additionally prove:

- Hybrid provisional/durable verification and negative outcomes.
- Archive integrity, privacy filtering, deterministic fingerprints, and duplicate replay.
- Dimensional coverage and `INSUFFICIENT_EVIDENCE`.
- Interval-union active time and separately labeled resource time.
- Expected versus actionable rejection classification.
- Atomic catalog rebuild and prior-catalog preservation on failure.
- Zero runtime/final-gate/GitHub mutation from evaluation commands.
- Added normal-path overhead remains within 250 ms or reports an operational-health degradation.
