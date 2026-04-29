# Feature Specification: CLI Distribution Packaging & Publishing

**Feature Branch**: `007-cli-distribution`
**Created**: 2026-04-28
**Status**: Draft
**Input**: User description: "CLI distribution skeleton exists but needs dependency fixes, CI publishing workflows, smoke tests, and installation documentation."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reliable Local Installation (Priority: P1)

As an end user, I want to install the CLI in a clean environment without encountering missing dependencies, so that it works reliably out of the box.

**Why this priority**: Without correct dependencies, the CLI is broken for all users, blocking adoption.

**Independent Test**: Can be fully tested by creating a clean virtual environment, installing the local package, and running a command that requires the previously missing dependencies (e.g., `gh-address-cr agent orchestrate status owner/repo 123`).

**Acceptance Scenarios**:

1. **Given** a completely clean Python virtual environment, **When** the user installs the `gh-address-cr` package, **Then** running `gh-address-cr agent orchestrate status` succeeds without `ModuleNotFoundError`.

---

### User Story 2 - Automated CI/CD Release (Priority: P1)

As a maintainer, I want automated CI workflows to build and publish the CLI package (wheel/sdist) on every semantic release, so that users can easily download the latest version from a public registry.

**Why this priority**: Automating the release process ensures consistent, error-free distribution of new versions to users.

**Independent Test**: Can be tested by triggering the release workflow in a dry-run or staging mode and verifying that the build artifacts are generated and upload steps succeed.

**Acceptance Scenarios**:

1. **Given** a new tag is pushed to the repository, **When** the GitHub Actions release workflow runs, **Then** it builds the wheel and sdist packages and publishes them to the registry.
2. **Given** a pull request is opened, **When** the CI workflow runs, **Then** it builds the package and performs a smoke test by installing it in an isolated environment.

---

### User Story 3 - Clear Installation Documentation (Priority: P2)

As a new user, I want clear instructions in the README on how to install the CLI using modern tools, so that I can get started quickly without needing to read development documentation.

**Why this priority**: Good documentation drives adoption and reduces support overhead for basic installation issues.

**Independent Test**: Can be tested by following the README instructions verbatim using `pipx` or `uv tool` and verifying a successful installation.

**Acceptance Scenarios**:

1. **Given** the repository's README file, **When** a user reads the "Installation" section, **Then** they find explicit commands for installing via `pipx` and `uv tool`.

### Edge Cases

- What happens if the desired package name `gh-address-cr` is already taken on the registry?
- How does the system handle installation in environments with older, incompatible Python versions?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The `pyproject.toml` MUST declare all required runtime dependencies, specifically including the `packaging` library.
- **FR-002**: The CI pipeline MUST include a smoke test job that builds the Python package (wheel and sdist) and verifies its installation in a clean environment.
- **FR-003**: The release workflow (`.github/workflows/release.yml`) MUST be updated to publish the built package artifacts to the chosen registry.
- **FR-004**: The package MUST be published exclusively to PyPI as the primary distribution channel for the Python CLI.
- **FR-005**: The `README.md` MUST provide end-user installation instructions using isolated environment tools (e.g., `pipx install gh-address-cr` and `uv tool install gh-address-cr`).

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: No direct impact on the runtime session state or GitHub IO.
- **CLI / Agent Contract Impact**: Ensures the CLI can be reliably invoked by the agent or user without crashing due to missing dependencies.
- **Evidence Requirements**: N/A for packaging.
- **Packaged Skill Boundary**: Modifies the repository root configuration (`pyproject.toml`, `.github/workflows`) and documentation, leaving the core `gh-address-cr/` skill logic untouched except for dependency declarations.
- **External Intake Replaceability**: N/A
- **Fail-Fast Behavior**: The CI smoke test MUST fail the build if the package cannot be installed or executed in a clean environment.

### Key Entities

- **Package Artifacts**: The generated `.whl` and `.tar.gz` files containing the CLI application.
- **Release Workflow**: The GitHub Actions pipeline responsible for automating semantic versioning and package distribution.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A fresh installation in an isolated Python environment can execute `gh-address-cr --help` and subcommands without dependency errors.
- **SC-002**: The CI workflow successfully builds and installs the package in a clean matrix job on every PR.
- **SC-003**: The README contains at least two distinct, copy-pasteable installation methods for end-users (e.g., `pipx` and `uv`).

## Assumptions

- The project uses standard Python build tools (`build`, `twine`, or modern equivalents) to generate artifacts.
- The `gh-address-cr` package name is available on the target registry (to be verified during implementation).
- Users have basic Python tooling (`pipx` or `uv`) installed on their systems to follow the documented instructions.
