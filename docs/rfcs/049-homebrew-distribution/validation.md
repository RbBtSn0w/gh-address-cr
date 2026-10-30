# Local implementation validation

Date: 2026-10-30

## Executed checks

- `scripts/dev_setup.sh`: completed; subsequent repository checks used the
  activated `.venv` with CPython 3.14.10.
- `ruff check src tests scripts/build_plugin_payload.py scripts/release`: passed.
- `python3 scripts/check_mypy_ratchet.py`: passed, zero errors across 94 source files.
- Complete `unittest` discovery after the P1 fix on the latest develop base:
  successful, 1,722 tests in 229.959 seconds
  (one skipped).
- Packaging/release/release-train regression suites: 82 tests passed.
- CLI `--help` and `agent manifest`: passed.
- Plugin payload generation and `--check`: passed.
- `actionlint` on CI, release, stable Homebrew and preview workflows: passed.
- Generated resource-formula Ruby syntax check: passed using rbenv Ruby.
- Standard isolated wheel/sdist build: passed in a temporary output directory.
- Wheel installation into a separate temporary virtual environment and
  `pip check`: passed.
- Installed-wheel agent journey: 18 tests passed.
- Installed-wheel version/help/manifest, current package data, SQLite and TLS:
  passed. A local-only OTLP receiver observed three real CLI export requests.

The initial restricted full-suite run failed on local socket/cache permissions
and environment-dependent evaluation fixtures. Re-running with normal local
permissions passed. No runtime-state or evaluation implementation was changed
to accommodate these failures.

## Tested publication boundaries

The reviewed P1 used `--no-all-checks` during bottle construction although
Homebrew requires that option to accompany `--merge`. The new regression test
failed for both first-build and explicit-rebuild cases before the fix, then
passed after removing the option from construction only. Both cases produce
validated bottle records; the merge command retains the option. A read-only
Homebrew parser probe confirms the corrected arguments reach the expected
missing-formula check instead of the invalid-option-combination error.

Fixture-based contracts cover standard formula generation; resource and source
identity validation; official resolver failure; immutable upload/readback;
atomic bottle recovery bundles; snapshot reuse without re-resolution; complete
four-target gating and merged-spec validation; preview provenance; and
publication-credential removal from external builds.

A real isolated local Git remote exercises a concurrent unrelated formula update
and a repeated successful publication. The update preserves the unrelated file
and does not add a second commit on replay. Telemetry tests cover root/subprocess
identity, success/failure exit codes, bounded diagnostics, argument privacy,
initialization failure and timed-out process cleanup.

## Acceptance still requiring release infrastructure

No GitHub workflow was dispatched, no Release asset or tap was written, and no
installed Homebrew package on the owner's system was changed. Version 3.21.2
was only built locally for smoke validation.

The four real macOS bottle builds, independent ordinary bottle installations,
prior-release upgrades, actual Python-version upgrades, six cache/timing samples
per target and the owner's normal-install compatibility check remain first-release
acceptance work. A Python reinstall check is implemented, but is distinct from
proof of upgrading between different interpreter versions.

The local wheel results establish package/install behavior, not Homebrew bottle
relocation, runner availability or bottle performance. Local CPython 3.12/3.13
execution was not repeated; their existing CI matrix remains intact.
