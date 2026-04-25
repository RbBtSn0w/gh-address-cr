# Quickstart: Runtime Native Refactor

## Verification Steps

### 1. Environment Setup
Ensure `PYTHONPATH` includes the `src` directory:
```bash
export PYTHONPATH=src
```

### 2. Run Native Unit Tests
Verify that the migrated logic passes its isolated tests and full regression suite:
```bash
python3 -m unittest tests.test_native_foundation tests.test_native_session tests.test_native_workflow
python3 -m unittest tests.test_native_github tests.test_native_intake tests.test_native_gate
python3 -m unittest discover -s tests
```

### 3. Verify No Legacy Imports
Check that the native packages do not depend on `legacy_scripts`:
```bash
rg -n "legacy_scripts|_legacy_module|SCRIPT_DIR|python_common|session_engine|ingest_findings|review_to_findings" \
  src/gh_address_cr/core src/gh_address_cr/github src/gh_address_cr/intake
```
(Expected: no matches).

### 4. Run CLI Integration
Test the native `review` flow via the CLI:
```bash
python3 -m gh_address_cr review <owner/repo> <pr_number>
```

### 5. Final Gate Check
Verify the native gate logic:
```bash
python3 -m gh_address_cr final-gate <owner/repo> <pr_number>
```

### 6. Package Size Snapshot
Current local size snapshot:

```text
gh-address-cr/                       860 KiB
src/gh_address_cr/                  1044 KiB
src/gh_address_cr/legacy_scripts/    436 KiB
native runtime excluding shims        ~608 KiB
```

### 7. Smoke Timing Snapshot
Local smoke timing from 5 runs with fake `gh` and temp state:

```text
review_waiting: rc=6 avg_seconds=0.3205 min_seconds=0.1508 max_seconds=0.8734
final_gate_empty_snapshot: rc=0 avg_seconds=0.1761 min_seconds=0.1748 max_seconds=0.1771
```

These are smoke baselines for this refactor branch; production parity should be checked again with a real PR session before release.
