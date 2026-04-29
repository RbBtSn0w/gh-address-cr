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
python3 -m unittest tests.test_native_runtime_boundary
python3 -m unittest discover -s tests
```

### 3. Verify No Legacy Imports
Check that the native packages do not depend on `legacy_scripts`:
```bash
rg -n "(gh_address_cr\.legacy_scripts|^from python_common|^import session_engine as engine|^from generate_reply)" \
  src/gh_address_cr/core src/gh_address_cr/github src/gh_address_cr/intake
```
(Expected: no matches).

### 3.1 Verify Public CLI Does Not Require Legacy Scripts
Check that public high-level commands route through native runtime code even when the packaged legacy script directory is unavailable:
```bash
python3 -m unittest tests.test_native_runtime_boundary
```

This does not require deleting compatibility scripts. It proves `review`, `threads`, `findings`, and `adapter` no longer depend on `legacy_scripts` as their primary runtime path.

### 3.2 Verify Session Snapshot Parity
Check that the native session engine preserves the legacy `session.json` shape byte-for-byte for a representative GitHub-thread and local-finding workflow:
```bash
python3 -m unittest tests.test_session_engine_parity
```

The fixture in `tests/fixtures/session_engine/legacy_native_session.json` is generated from the legacy implementation and compared as exact JSON text, not as a normalized object.

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
skill/                       776 KiB
src/gh_address_cr/                  1240 KiB
src/gh_address_cr/legacy_scripts/    352 KiB
native runtime excluding shims        ~888 KiB
```

### 7. Smoke Timing Snapshot
Local smoke timing from 5 runs with fake `gh` and temp state:

```text
review_waiting: rc=6 avg_seconds=0.3205 min_seconds=0.1508 max_seconds=0.8734
final_gate_empty_snapshot: rc=0 avg_seconds=0.1761 min_seconds=0.1748 max_seconds=0.1771
```

These are smoke baselines for this refactor branch; production parity should be checked again with a real PR session before release.
