# Feature Specification: CLI and Skill Synchronization

**Feature Branch**: `012-skill2cli`
**Created**: 2026-05-30
**Status**: Complete
**Last Audited**: 2026-06-02
**Input**: Three-phase migration from duplicated skill-layer Python shims to a
single runtime-owned CLI execution surface. Phase 1 introduced a temporary sync
guard, Phase 2 moved implementation logic into package handlers, and Phase 3
removed Python scripts from the packaged skill payload so agents execute
`gh-address-cr` directly.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Runtime CLI Is The Skill Execution Surface (Phase 3 - Complete)

As a developer/maintainer, I want the packaged skill and Codex plugin to route
all executable work through the installed `gh-address-cr` CLI, so that the skill
cannot drift into a second implementation of review handling, GitHub side
effects, or completion gating.

**Acceptance Scenarios**:
1. **Given** the plugin payload is built, **When** I inspect the packaged skill,
   **Then** it contains no `scripts/` directory or Python shim entrypoints.
2. **Given** `skill/SKILL.md` and `skill/agents/openai.yaml`, **When** they
   describe execution, **Then** they point to `gh-address-cr` and
   `python3 -m gh_address_cr` instead of skill-local scripts.
3. **Given** an agent receives an `ActionRequest`, **When** it follows the
   `resume_command`, **Then** the command targets the runtime CLI and not a
   removed skill shim.

---

### User Story 2 - Runtime Package Keeps Compatibility Without Owning Skill Logic (Phase 3 - Complete)

As a runtime maintainer, I want any remaining compatibility files to live inside
the Python package and delegate to runtime-owned handlers, so that old low-level
entrypoints remain explicit implementation details while public high-level
commands stay native.

**Acceptance Scenarios**:
1. **Given** high-level commands such as `review`, `address`, `threads`,
   `findings`, and `adapter`, **When** they run, **Then** they do not require
   `src/gh_address_cr/legacy_scripts/`.
2. **Given** package-internal legacy command surfaces are invoked, **When** they
   execute, **Then** they delegate to native package modules and do not duplicate
   state-machine logic in the skill payload.
3. **Given** current public docs and skill references, **When** they mention
   removed skill-shim paths, **Then** the mention is limited to upgrade or
   superseded-history context and not presented as a runnable path.

---

### User Story 3 - Distribution And CI Guard Against Regression (Phase 3 - Complete)

As a release maintainer, I want the plugin payload, tests, and workflows to prove
that the skill remains a thin adapter, so that future changes cannot
accidentally restore duplicated skill scripts or stale execution instructions.

**Acceptance Scenarios**:
1. **Given** the repo-local plugin builder runs in check mode, **When** the
   committed payload matches `skill/`, **Then** it exits successfully.
2. **Given** CI or release workflows run, **When** they validate the repo,
   **Then** they check the plugin payload and do not run obsolete script-sync
   guards.
3. **Given** the full local verification suite runs, **When** it completes,
   **Then** linting, unit tests, CLI smoke, manifest smoke, payload check, and
   whitespace checks all pass using the current test suite.

## Edge Cases

- **Legacy runtime compatibility**: `src/gh_address_cr/legacy_scripts/` may
  remain as package-internal compatibility shims, but high-level public commands
  must not depend on that directory.
- **Removed skill-shim usage**: Upgrade docs may mention
  `python3 skill/scripts/cli.py` only to say that path has been removed and users
  must install/run the runtime CLI.
- **Historical specs**: Older feature specs may retain old shim examples only
  when they are explicitly marked as superseded by this feature.
- **Plugin payload drift**: Generated plugin files must stay reproducible from
  `skill/` via `scripts/build_plugin_payload.py --check`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The packaged skill payload MUST NOT contain a `scripts/` directory
  or Python execution shims.
- **FR-002**: `skill/SKILL.md`, `skill/agents/openai.yaml`, and skill-owned
  references MUST use `gh-address-cr` CLI commands as the execution surface.
- **FR-003**: The Codex plugin payload under `plugin/gh-address-cr/` MUST be
  generated from `skill/` and MUST include exactly one packaged skill named
  `gh-address-cr`.
- **FR-004**: CI and release workflows MUST validate the generated plugin
  payload and MUST NOT require obsolete skill-script synchronization.
- **FR-005**: High-level public commands (`review`, `address`, `threads`,
  `findings`, and `adapter`) MUST run through native runtime code without
  requiring package-internal legacy script files.
- **FR-006**: `ActionRequest.resume_command` values MUST reject removed
  skill-local shim paths and target the runtime CLI instead.
- **FR-007**: Current public docs MUST NOT present `skill/scripts` or
  `scripts/cli.py` as runnable command paths. Upgrade docs may mention the old
  path only as removed.
- **FR-008**: Historical specs that still contain old shim paths MUST be marked
  as superseded by `specs/012-cli-skill-sync`.
- **FR-009**: Verification MUST use the current unit-test suite result instead
  of a hard-coded historical test count.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: Preserves deterministic ownership by keeping
  runtime state, GitHub side effects, leases, telemetry, and final-gate logic in
  the CLI/runtime package.
- **CLI / Agent Contract Impact**: Confirms that the stable public agent surface
  is `gh-address-cr` plus structured `ActionRequest`/`ActionResponse` protocol
  commands.
- **Evidence Requirements**: Completion evidence comes from runtime CLI smoke,
  manifest output, payload check, lint, unit tests, and `git diff --check`.
- **Packaged Skill Boundary**: The installed skill remains a thin adapter and
  behavioral policy layer under `skill/`.
- **External Intake Replaceability**: The migration does not couple the runtime
  to any specific review producer.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `git ls-files skill plugin/gh-address-cr` shows no packaged
  `scripts/` Python shim paths.
- **SC-002**: `skill/SKILL.md` and `skill/agents/openai.yaml` contain runtime
  CLI instructions and no `scripts/cli.py` execution path.
- **SC-003**: `python3 scripts/build_plugin_payload.py --check` reports the
  plugin payload is up to date.
- **SC-004**: The current full unit-test suite passes without relying on a fixed
  historical test count.
- **SC-005**: `python3 -m gh_address_cr --help` and
  `python3 -m gh_address_cr agent manifest` run successfully.
- **SC-006**: Public docs and current feature artifacts no longer direct agents
  to removed skill-local scripts.
