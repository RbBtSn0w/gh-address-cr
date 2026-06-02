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

## Runtime Package Naming Checks

```bash
python3 -m unittest \
  tests.test_runtime_packaging.RuntimePackagingTest.test_current_runtime_commands_are_not_handler_package_named \
  tests.test_runtime_packaging.RuntimePackagingTest.test_runtime_cli_has_no_legacy_or_handler_script_dispatcher \
  tests.test_runtime_packaging.RuntimePackagingTest.test_installed_runtime_does_not_carry_legacy_command_scripts
rg -n "gh_address_cr\\.(legacy_handlers|command_handlers)|src/gh_address_cr/(legacy_handlers|command_handlers)|(legacy_handlers|command_handlers)" \
  src tests README.md skill plugin/gh-address-cr/skills/gh-address-cr specs/013-remove-legacy-compat
```

Expected result: the runtime package exposes current helper implementations
through `gh_address_cr.commands`; `gh_address_cr.legacy_handlers` and
`gh_address_cr.command_handlers` are not importable or packaged. Remaining
handler-name mentions are limited to 013 contracts, tasks, or tests that verify
the removed names stay absent.

## Final Verification Evidence

Captured on 2026-06-02:

- `ruff check src tests` -> PASS (`All checks passed!`)
- `python3 -m unittest discover -s tests` -> PASS (`Ran 510 tests in 122.567s`, `OK`)
- `python3 -m gh_address_cr --help` -> PASS
- `python3 -m gh_address_cr agent manifest` -> PASS (`status: MANIFEST_READY`)
- `python3 scripts/build_plugin_payload.py --check` -> PASS (`plugin payload is up to date`)
- `git diff --check` -> PASS
- `python3 -m gh_address_cr cr-loop --help` -> unsupported legacy command, exit `2`
- `python3 -m gh_address_cr session-engine --help` -> unsupported legacy command, exit `2`
- `python3 -m gh_address_cr clean-state --help` -> unsupported legacy command, exit `2`
- `python3 -m unittest tests.test_runtime_packaging.RuntimePackagingTest.test_current_runtime_commands_are_not_handler_package_named tests.test_runtime_packaging.RuntimePackagingTest.test_runtime_cli_has_no_legacy_or_handler_script_dispatcher tests.test_runtime_packaging.RuntimePackagingTest.test_installed_runtime_does_not_carry_legacy_command_scripts` -> PASS
- Superb verification evidence archived at `.specify/evidence/013-remove-legacy-compat/20260602T115654Z.md`
