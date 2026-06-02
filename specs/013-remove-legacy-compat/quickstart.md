# Quickstart: Remove Legacy Compatibility

## Baseline

```bash
ruff check src tests
python3 -m unittest discover -s tests
python3 -m gh_address_cr --help
python3 -m gh_address_cr agent manifest
scripts/build_plugin_payload.py --check
git diff --check
```

## Supported Workflow Checks

```bash
python3 -m gh_address_cr --help
python3 -m gh_address_cr review --help
python3 -m gh_address_cr address --help
python3 -m gh_address_cr threads --help
python3 -m gh_address_cr findings --help
python3 -m gh_address_cr adapter --help
python3 -m gh_address_cr review-to-findings --help
python3 -m gh_address_cr submit-feedback --help
python3 -m gh_address_cr submit-action --help
python3 -m gh_address_cr final-gate --help
```

## Unsupported Legacy Checks

```bash
python3 -m gh_address_cr cr-loop --help
python3 -m gh_address_cr session-engine --help
python3 -m gh_address_cr clean-state --help
```

Expected result: each unsupported legacy command exits non-zero, identifies the
usage as unsupported legacy behavior, and points to the current supported
workflow surface.

## Documentation Checks

```bash
python3 -m unittest tests.test_skill_docs tests.test_plugin_packaging
rg -n "legacy_scripts|cr-loop|session-engine" README.md skill plugin/gh-address-cr/skills/gh-address-cr
```

Expected result: active guidance does not present removed compatibility paths
as runnable instructions. Any retained historical mention is marked as
superseded or archival.

## Final Verification Evidence

Captured on 2026-06-02:

- `ruff check src tests` -> PASS (`All checks passed!`)
- `python3 -m unittest discover -s tests` -> PASS (`Ran 533 tests in 90.670s`, `OK`)
- `python3 -m gh_address_cr --help` -> PASS
- `python3 -m gh_address_cr agent manifest` -> PASS (`status: MANIFEST_READY`)
- `python3 scripts/build_plugin_payload.py --check` -> PASS (`plugin payload is up to date`)
- `git diff --check` -> PASS
- `python3 -m gh_address_cr cr-loop --help` -> unsupported legacy command, exit `2`
- `python3 -m gh_address_cr session-engine --help` -> unsupported legacy command, exit `2`
- `python3 -m gh_address_cr clean-state --help` -> unsupported legacy command, exit `2`
