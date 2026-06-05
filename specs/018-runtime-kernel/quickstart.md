# Quickstart: Runtime Kernel

## Prerequisites

Run from the repository root on branch `018-runtime-kernel`.

## Focused Validation

Run the focused runtime-kernel tests:

```bash
python3 -m unittest tests.test_runtime_kernel
```

Expected outcome:

- deterministic projection replay passes
- reordered facts produce the same projection
- unresolved, stale, reopened, and already-resolved thread scenarios route through projection/policy
- final-gate eligibility is blocked while required review work remains
- command plans are idempotent and non-executing
- reporting-only facts do not complete review work or create recursive blockers

## Repository Validation

Run the standard local verification gate:

```bash
ruff check src tests
python3 -m unittest discover -s tests
python3 -m gh_address_cr --help
```

Expected outcome:

- lint passes
- full unit suite passes
- CLI smoke command prints help successfully

## Contract Inspection

Review these artifacts before expanding the slice into existing workflow paths:

```text
specs/018-runtime-kernel/contracts/review-thread-kernel.md
specs/018-runtime-kernel/contracts/command-plan.md
specs/018-runtime-kernel/contracts/telemetry-reporting-boundary.md
```

Do not route existing GitHub side-effecting commands through the kernel until the executor boundary and public CLI compatibility tests are explicitly planned.
