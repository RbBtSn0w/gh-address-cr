# Contract: Evaluation CLI

The `evaluation` namespace is an advanced additive public surface. It does not replace `review`, `address`, `telemetry`, or `final-gate`.

## Observe A Later Reviewer Round

```text
gh-address-cr evaluation observe <owner/repo> <pr_number> --run-id <run_id> [--format json|markdown]
```

Behavior:

- Performs read-only GitHub queries for PR head, submitted review rounds, and review threads.
- Appends public-safe `evaluation-observation.v1` rows using deterministic fingerprints.
- Stores only the reviewer's relation to the concern (`original_concern_author`, `other_reviewer`, or `unknown`), not a username or private identity.
- Never replies, resolves, publishes, submits a review, or changes runtime session state.
- Duplicate observations return success with `duplicate_count` and do not increase samples.

Success reason codes:

- `EVALUATION_OBSERVATION_RECORDED`
- `EVALUATION_OBSERVATION_DUPLICATE`
- `EVALUATION_NO_SUPPORTED_OBSERVATION`

## Rebuild The Catalog

```text
gh-address-cr evaluation rebuild [--repo <owner/repo>] [--pr-number <number>] [--format json|markdown]
```

Behavior:

- Scans supported archives and evaluation observation ledgers.
- Builds a temporary SQLite catalog, validates counts and fingerprints, and atomically replaces the prior catalog.
- Leaves the prior valid catalog untouched on failure.
- Does not modify archive contents or runtime workspaces.

Required output fields:

- `status`, `reason_code`, `catalog_schema_version`, `archive_count`, `run_count`, `concern_count`, `observation_count`, `skipped_count`, `diagnostics`, `catalog_artifact`, `source_fingerprint`.

## Show One Run Or PR

```text
gh-address-cr evaluation show <owner/repo> <pr_number> [--run-id <run_id>] [--format json|markdown]
```

Behavior:

- Reads the derived catalog only.
- Reports concern and run records with dimensional coverage and evidence deficits.
- Returns non-zero if the catalog is missing/corrupt; it does not silently rebuild.

## Compare Runtime Versions

```text
gh-address-cr evaluation compare --baseline-version <version> --candidate-version <version> [--repo <owner/repo>] [--format json|markdown] [--output <path>]
```

Behavior:

- Selects supported matched cohorts from the catalog.
- Returns independent quality, economics, and operational-health vectors.
- Writes a derived JSON report only when `--output` is provided.
- Returns `INSUFFICIENT_EVIDENCE` rather than an improvement claim when evidence requirements fail.

## Exit Codes

- `0`: command completed and output is valid, including `INSUFFICIENT_EVIDENCE` as a valid evaluation conclusion.
- `2`: invalid arguments, missing required input, or unsupported schema/format.
- `4`: requested catalog/run/cohort not found.
- `5`: malformed, unsafe, ambiguous, integrity-failed, or corrupt evaluation evidence/catalog.

## Failure Reason Codes

- `EVALUATION_INPUT_INVALID`
- `EVALUATION_INPUT_UNSAFE`
- `UNSUPPORTED_EVALUATION_SCHEMA`
- `EVALUATION_ARCHIVE_INTEGRITY_FAILED`
- `EVALUATION_OBSERVATION_AMBIGUOUS`
- `EVALUATION_CATALOG_MISSING`
- `EVALUATION_CATALOG_CORRUPT`
- `EVALUATION_REBUILD_FAILED`
- `EVALUATION_RUN_NOT_FOUND`
- `INSUFFICIENT_EVIDENCE`

## Failure Boundary

- Explicit evaluation commands are fail-loud and return stable machine reason codes.
- Missing or damaged evaluation evidence does not change `review`, `address`, reply, resolve, publish, or final-gate outcomes.
- Final-gate may surface evaluation capture diagnostics but must preserve its existing exit code and completion counts.
