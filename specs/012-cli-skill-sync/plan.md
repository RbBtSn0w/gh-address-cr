# Implementation Plan: CLI and Skill Synchronization (Phase 3 Closeout)

**Branch**: `012-skill2cli` | **Date**: 2026-06-02 | **Spec**: [spec.md](./spec.md)

## Goal Description

Close the CLI/skill migration by making the current artifacts match the
implemented runtime boundary: the packaged skill is a thin adapter, the runtime
CLI owns executable work, and historical shim instructions are clearly marked as
superseded.

## Architecture

The runtime implementation remains in `src/gh_address_cr/` and exposes the
public console command `gh-address-cr`. The packaged skill under `skill/` carries
behavioral policy, references, and assistant hints only. The plugin payload under
`plugin/gh-address-cr/` is generated from `skill/` and does not contain a Python
execution surface.

Package-internal `src/gh_address_cr/legacy_scripts/` files may remain for
backward-compatible low-level command dispatch, but high-level public commands
must run through native runtime code and tests must prove that boundary.

## Constitution Check

- **Control plane ownership**: PASS. State transitions, GitHub side effects,
  leases, telemetry, and final-gate logic remain runtime-owned.
- **Public CLI contract**: PASS. Current execution instructions target
  `gh-address-cr` and `python3 -m gh_address_cr`.
- **Evidence-first handling**: PASS. The migration does not bypass
  reply/resolve evidence or final-gate requirements.
- **Packaged skill boundary**: PASS. `skill/` is policy/reference payload only;
  no packaged Python scripts remain.
- **External intake replaceability**: PASS. Review producers still feed
  normalized findings into the runtime.
- **Testable contracts**: PASS. Regression tests cover docs, payload packaging,
  native high-level command routing, and superseded historical shim references.

## Proposed Changes

### Current Feature Artifacts

- Update `specs/012-cli-skill-sync/spec.md` to mark Phase 3 complete and replace
  obsolete sync-era requirements with current CLI-owned requirements.
- Update this plan so the verification path is the current closeout gate, not a
  removed shim-sync workflow.
- Update `specs/012-cli-skill-sync/tasks.md` with a closeout audit phase and
  current verification evidence.

### Historical Specs

- Mark older specs that still mention `skill/scripts` or `scripts/cli.py` as
  superseded by `specs/012-cli-skill-sync`.
- Keep the historical text intact where it documents old behavior, but make the
  current authority explicit so agents do not treat those examples as runnable
  instructions.

### Executable Guardrails

- Add an artifact contract test that checks:
  - `012` artifacts name the current branch and completed closeout state.
  - The current plan no longer references removed sync tooling.
  - Hard-coded historical unit-test counts are not used as success criteria.
  - Any older spec with skill-script paths contains the superseded marker.
- Preserve existing guards in `tests/test_skill_docs.py`,
  `tests/test_plugin_packaging.py`, and `tests/test_native_runtime_boundary.py`.

## Verification Plan

Run the local verification gate with Python 3.10+:

```bash
ruff check src tests
python3 -m unittest discover -s tests
python3 -m gh_address_cr --help
python3 -m gh_address_cr agent manifest
python3 scripts/build_plugin_payload.py --check
git diff --check
```

The unit-test assertion is intentionally count-agnostic: the current suite count
may change as tests are added or removed, but the full suite must pass.
