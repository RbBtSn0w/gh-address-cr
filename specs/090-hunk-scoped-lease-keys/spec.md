# Feature Spec: Hunk-Scoped Lease Conflict Keys

## Summary

Allow independent same-file review threads to be leased concurrently when reliable line ranges do not overlap.

## Behavior

- Items with reliable `line`/`end_line` metadata use `hunk:<path>:<start>-<end>` conflict keys.
- Non-overlapping hunks in the same file may hold active leases concurrently.
- Overlapping hunks remain mutually exclusive.
- Missing or ambiguous line metadata falls back to file-level locking.

## Owner Boundary

Conflict-key calculation and active lease conflict checks live in runtime lease code.

## Verification

- `python3 -m unittest tests.test_issue78_agent_experience.Issue78LeaseScopeTests`
- `python3 -m unittest tests.test_lease_scheduling`
- `ruff check src tests`
- `python3 -m unittest discover -s tests`
- `python3 -m gh_address_cr --help`
