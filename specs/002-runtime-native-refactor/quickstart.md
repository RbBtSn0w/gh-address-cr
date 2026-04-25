# Quickstart: Runtime Native Refactor

## Verification Steps

### 1. Environment Setup
Ensure `PYTHONPATH` includes the `src` directory:
```bash
export PYTHONPATH=src
```

### 2. Run Native Unit Tests
Verify that the migrated logic passes its isolated tests:
```bash
python3 -m unittest discover -s tests
```

### 3. Verify No Legacy Imports
Check that the native packages do not depend on `legacy_scripts`:
```bash
grep -r "legacy_scripts" src/gh_address_cr/core/ src/gh_address_cr/github/ src/gh_address_cr/intake/
```
(Expected: No matches, or only in comments/shims).

### 4. Run CLI Integration
Test the native `review` flow via the CLI:
```bash
python3 src/gh_address_cr/cli.py review <owner/repo> <pr_number>
```

### 5. Final Gate Check
Verify the native gate logic:
```bash
python3 src/gh_address_cr/cli.py final-gate <owner/repo> <pr_number>
```
