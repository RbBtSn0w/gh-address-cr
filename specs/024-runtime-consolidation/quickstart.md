# Quickstart: Evidence-Gated Runtime Consolidation

Validation guide proving the migration framework is reversible, side-effect-free,
and evidence-gated. Implementation details live in `tasks.md`; schemas live in
[contracts/](contracts/README.md) and [data-model.md](data-model.md).

## Prerequisites

- Python 3.10+ with the package installed for development: `pip install -e .`
- Repo-root working directory; no live GitHub credentials required (parity and
  status are offline/read-only).

## Scenario 1 — Single authoritative owner per axis (SC-001, FR-005)

```bash
python3 -m gh_address_cr consolidation status --json
```

Expected: an `authority-map.v1` document with exactly one entry per axis. Inject a
duplicate-owner fixture and re-run:

- Expected: non-zero exit, reason code `DUPLICATE_STATE_OWNER`, no partial output
  treated as authoritative.

## Scenario 2 — Deterministic, side-effect-free parity (SC-002, SC-003, FR-007)

```bash
python3 -m gh_address_cr consolidation parity --slice slice-check-state --facts tests/consolidation/fixtures/check_state_facts.json --json
```

Expected: a `parity-report.v1` with `side_effects_executed: 0`, matching
`projection_match` / `decision_match` / `command_plan_match` for a supported
fixture, and identical output across repeated runs on the same `fact_digest`.
Assert zero `gh` invocations (contract test uses a GitHub client that fails on any
call).

## Scenario 3 — Rollout gate blocks on insufficient evidence (SC-004, SC-008)

```bash
# Promote to opt-in first, then attempt to promote to default with only
# provisional feature-023 evidence
python3 -m gh_address_cr consolidation rollout --slice slice-check-state --to opt_in
python3 -m gh_address_cr consolidation rollout --slice slice-check-state --to default
```

Expected: blocked, non-zero exit, reason code `INSUFFICIENT_EVIDENCE`. With an
unexplained parity difference present, expect `PARITY_DIFF`. `shadow`/`opt_in`
transitions succeed on provisional evidence; `default` requires durable
feature-023 evidence supplied explicitly via an `evaluation.v1` file, and later
promotion gates may also consume an explicit `parity-report.v1` file.

## Scenario 4 — Reversible rollback (SC-005, FR-016)

```bash
python3 -m gh_address_cr consolidation rollout --slice slice-check-state --to opt_in
# ... exercise the enabled slice ...
python3 -m gh_address_cr consolidation rollout --slice slice-check-state --to shadow
```

Expected: after reverting, `session.json` runtime facts and `evidence.jsonl`
execution records are byte-for-byte unchanged; review truth is not reconstructed
from any report. A rollback trigger fixture (quality/health breach) auto-selects
the reversal stage.

## Scenario 5 — Independent optimization hypotheses (SC-007, FR-011/FR-012)

- Enable `output_truncation` and confirm `--full` still returns untruncated
  output and truncation is **not** the default until its gate passes.
- Disable `command_session` and confirm the non-session path still completes a
  supported review flow.
- Each hypothesis's stage changes without altering the other two.

## Scenario 6 — Unsupported cohort stays on the supported path (SC-006)

Run status against a PR cohort outside the slice's `supported_cohort`.

```bash
python3 -m gh_address_cr consolidation status --cohort unsupported-host --json
```

- Expected: the axis reports `legacy` authority for that cohort; no candidate
  path is exercised.

## Full verification suite

```bash
pip install -e .
ruff check src tests
python3 -m unittest discover -s tests
python3 -m gh_address_cr --help
python3 -m gh_address_cr consolidation status --json
```

Expected: all pass; `consolidation` help lists `status`, `parity`, `rollout`,
and the `status`/`rollout` surfaces expose the optional `--cohort` and
`--evidence-file` controls needed for executable migration validation. The
existing `review` / `final-gate` behavior and machine summaries are unchanged.
