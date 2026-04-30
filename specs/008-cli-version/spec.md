# Feature Specification: CLI Version Query

**Feature Branch**: `008-cli-version`  
**Created**: 2026-04-30  
**Status**: Verified
**Input**: User description: "少了知道当前cli的版本号的功能，需要补充一个新功能。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Standard Version Flag (Priority: P1)

As a developer or agent, I want to quickly check which version of `gh-address-cr` I am running using a standard `--version` flag, so I can confirm compatibility or report bugs accurately.

**Why this priority**: High. This is the industry-standard way to query CLI versions and is essential for troubleshooting and environment verification.

**Independent Test**: Running `gh-address-cr --version` returns a semantic version string (e.g., `2.2.1`).

**Acceptance Scenarios**:

1. **Given** the CLI is installed, **When** I run `gh-address-cr --version`, **Then** the system outputs the current version number and exits with code 0.
2. **Given** the CLI is installed, **When** I run `gh-address-cr -v` (optional alias), **Then** the system outputs the current version number.

---

### User Story 2 - Version Subcommand (Priority: P2)

As a user who prefers subcommands, I want to run `gh-address-cr version` to see the version information.

**Why this priority**: Medium. Provides consistency with other tools that use subcommands for metadata.

**Independent Test**: Running `gh-address-cr version` returns the version string.

**Acceptance Scenarios**:

1. **Given** the CLI is installed, **When** I run `gh-address-cr version`, **Then** the system outputs the current version number and exits with code 0.

---

### Edge Cases

- **Mixed Flags**: Running `gh-address-cr --version review` should prioritize showing the version and potentially exit, or show the version as part of a preflight check. Industry standard is usually for `--version` to be a terminal command that prints and exits.
- **Malformed Input**: If used with invalid arguments, `--version` should still function if it is the primary intent.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The CLI MUST support a `--version` global flag.
- **FR-002**: The CLI SHOULD support a `-v` shorthand flag for version query.
- **FR-003**: The CLI MUST support a `version` subcommand.
- **FR-004**: The version output MUST match the `__version__` defined in `src/gh_address_cr/__init__.py`.
- **FR-005**: The output format MUST be clear and machine-parsable (e.g., just the version string or `gh-address-cr vX.Y.Z`).
- **FR-006**: Querying the version MUST NOT require a GitHub token or internet connectivity.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: No impact. Version query is a metadata operation that does not affect session state or PR orchestration.
- **CLI / Agent Contract Impact**: Adds new commands/flags to the CLI contract. Does not change existing high-level command behavior.
- **Evidence Requirements**: N/A for this feature.
- **Packaged Skill Boundary**: Changes affect `src/gh_address_cr/cli.py`.
- **External Intake Replaceability**: No impact.
- **Fail-Fast Behavior**: Should fail loudly if the version cannot be determined (unlikely in this architecture).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: User can obtain the CLI version in < 1 second using standard flags.
- **SC-002**: 100% of version queries return a valid semantic version string.
- **SC-003**: Version output remains consistent across all supported entry points (installed CLI and skill scripts).

## Assumptions

- **Version source**: `src/gh_address_cr/__init__.py`'s `__version__` is the single source of truth.
- **Output stream**: Version information is written to `stdout`.
