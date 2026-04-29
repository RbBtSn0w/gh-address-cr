# Requirements Checklist: CLI Distribution Packaging & Publishing

**Purpose**: Validate specification and plan quality before implementation.
**Created**: 2026-04-28
**Updated**: 2026-04-29
**Feature**: [specs/007-cli-distribution/spec.md](../spec.md)

**Note**: This is the single checklist for feature 007. It consolidates the
baseline requirements-quality checks and the spec/plan review checks.

## Content Quality

- [x] Implementation details are limited to release-engineering constraints that materially affect distribution
- [x] Focused on user value and business needs
- [x] Written for maintainers and release reviewers
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are objective and tied to install/release outcomes
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] Package/release details in the specification are intentional distribution requirements

## Notes

- Baseline checklist says the spec is ready for planning.
- The detailed review items below identify issues to resolve before implementation.

## Spec/Plan Review - Requirement Completeness

- [x] CHK001 Are runtime CLI distribution and packaged skill installation explicitly separated as two distribution surfaces? [Completeness, Spec §Distribution Boundary/FR-010, Plan §Distribution Boundary]
- [x] CHK002 Are all runtime dependencies required by installable CLI subcommands documented in package requirements, beyond the known `packaging` dependency? [Completeness, Spec §FR-001]
- [x] CHK003 Is the PyPI package-name availability edge case promoted from an open question to an explicit requirement or implementation task? [Gap, Spec §Edge Cases]
- [x] CHK004 Are PyPI publishing credentials, trusted publishing setup, and required repository environment assumptions documented? [Gap, Spec §FR-008, Plan §Release Design]
- [x] CHK005 Are build artifact expectations defined for both wheel and sdist, including whether artifacts must be uploaded on PRs or only releases? [Completeness, Spec §US2/FR-002/FR-005]
- [x] CHK006 Are user installation paths defined for released packages, GitHub-direct installs, and local development installs without mixing their intended audiences? [Completeness, Spec §FR-010]

## Spec/Plan Review - Requirement Clarity

- [x] CHK007 Is "running `gh-address-cr agent orchestrate status` succeeds" clarified to distinguish dependency/import success from expected non-zero session-state results? [Ambiguity, Spec §US1]
- [x] CHK008 Is "chosen registry" consistently named as PyPI everywhere, without leaving registry selection ambiguous? [Clarity, Spec §FR-007]
- [x] CHK009 Is "published exclusively to PyPI" clarified to allow or exclude GitHub Release artifacts created by semantic-release? [Ambiguity, Spec §Clarifications/FR-007]
- [x] CHK010 Are `pipx` and `uv tool` install commands specified with the exact package name, Python version expectations, and post-install smoke command? [Clarity, Spec §FR-011]
- [x] CHK011 Is the required clean-environment smoke command defined with exact expected output class and allowed failure reason codes? [Clarity, Spec §US1]

## Spec/Plan Review - Requirement Consistency

- [x] CHK012 Do release trigger and version requirements align between the semantic-release-on-main model and Python artifact version synchronization? [Consistency, Spec §FR-013, Plan §Package Version Synchronization]
- [x] CHK013 Does README and skill compatibility documentation preserve the packaged skill boundary while allowing repo-root README install updates? [Consistency, Spec §FR-010, Plan §Distribution Boundary]
- [x] CHK014 Are CI matrix requirements consistent with the repository's current Python 3.10+ support and existing CI matrix? [Consistency, Plan §Technical Context]
- [x] CHK015 Are runtime package publishing requirements consistent with the semantic-release version source and Python package artifact version ownership? [Consistency, Spec §FR-013, Plan §Package Version Synchronization]

## Spec/Plan Review - Acceptance Criteria Quality

- [x] CHK016 Can SC-001 be objectively evaluated for each critical subcommand class (`--help`, `agent manifest`, `agent orchestrate`, `final-gate`)? [Measurability, Spec §SC-001]
- [x] CHK017 Is SC-002 measurable enough to distinguish package build, package install, and installed CLI execution as separate gates? [Measurability, Spec §SC-002]
- [x] CHK018 Are README installation success criteria scoped to end-user runtime CLI installation separately from developer setup and packaged skill installation? [Measurability, Spec §SC-004/SC-005]
- [x] CHK019 Are release workflow success criteria defined for dry-run/staging validation before publishing to production PyPI? [Gap, Spec §US3/SC-003]

## Spec/Plan Review - Scenario Coverage

- [x] CHK020 Are primary install flows covered for PyPI, GitHub source install, and local editable development install? [Coverage, Spec §US4/FR-010]
- [x] CHK021 Are exception flows specified for missing build tooling, unsupported Python versions, missing PyPI credentials, and package-name conflict? [Coverage, Spec §Edge Cases]
- [x] CHK022 Are recovery requirements defined for failed or partially completed package publishing runs? [Gap, Recovery Flow]
- [x] CHK023 Are upgrade and reinstall scenarios defined for users moving from skill-shim usage to the installed runtime CLI? [Gap, Spec §US4/FR-014]

## Spec/Plan Review - Dependencies & Assumptions

- [x] CHK024 Are build-time dependencies (`setuptools`, `build`, `twine` or `pypa/gh-action-pypi-publish`) clearly separated from runtime dependencies? [Dependency, Plan §Technical Context]
- [x] CHK025 Are assumptions about user tooling (`pipx`, `uv`) paired with fallback instructions or explicitly scoped out? [Assumption, Spec §Assumptions]
- [x] CHK026 Are external service dependencies for PyPI publishing documented with required credentials model, permissions, and failure handling? [Dependency, Spec §FR-008/FR-009]

## Spec/Plan Review - Traceability

- [x] CHK027 Does every task in `tasks.md` map back to at least one user story, functional requirement, or success criterion? [Traceability, Spec §Requirements]
- [x] CHK028 Are implementation tasks present for every documented edge case that affects release readiness? [Traceability, Spec §Edge Cases]
- [x] CHK029 Is there a clear requirement-to-CI-gate mapping for dependency declaration, wheel/sdist build, isolated install, and CLI smoke? [Traceability, Plan §Project Structure]
