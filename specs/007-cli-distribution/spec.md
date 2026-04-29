# Feature Specification: CLI Distribution Packaging & Publishing

**Feature Branch**: `007-cli-distribution`
**Created**: 2026-04-28
**Updated**: 2026-04-29
**Status**: Verified
**Input**: User description: "CLI distribution skeleton exists but needs dependency fixes, CI publishing workflows, smoke tests, and installation documentation."

## Clarifications

### Session 2026-04-29

- Q: What is being distributed? -> A: The Python runtime CLI package (`gh-address-cr`) is distributed through PyPI. The packaged skill (`gh-address-cr/`) remains installed through the skills installer and is not bundled as the Python package's primary user-facing install target.
- Q: Does "PyPI exclusive" forbid GitHub Releases? -> A: No. PyPI is the exclusive package registry and the only documented end-user CLI install source for released packages. GitHub Releases may still contain semantic-release notes, tags, source archives, and optional build attestations, but they must not be documented as the primary CLI package registry.
- Q: What does the clean-install smoke test mean? -> A: It proves the installed package imports all runtime dependencies and starts critical CLI command groups. Business-state failures such as a missing PR session are acceptable only when emitted as structured CLI output, not as import errors or Python tracebacks.
- Q: How is package-name availability handled? -> A: Before enabling production PyPI publishing, the implementation must verify that `gh-address-cr` is available or already controlled by the project owner. If it is unavailable, implementation must stop and require a naming decision.
- Q: What publishing credential model is expected? -> A: PyPI Trusted Publishing through GitHub OIDC is required for production publishing. Long-lived PyPI API tokens must not be used for production publishing unless a separate explicit release-policy change approves that fallback.
- Q: How is the Python package version determined? -> A: The built wheel and sdist version must match the semantic-release version for the release. The release workflow must fail before publishing if package metadata does not match the semantic-release version or tag being released.

## Distribution Boundary

This feature has three distinct install surfaces:

1. **Released runtime CLI**: `pipx install gh-address-cr` or `uv tool install gh-address-cr` from PyPI. This installs the `gh-address-cr` executable and `python -m gh_address_cr`.
2. **GitHub direct runtime install**: `pipx install git+https://github.com/RbBtSn0w/gh-address-cr.git` or equivalent. This is a pre-release/manual validation path, not the primary stable release channel.
3. **Packaged skill install**: `npx skills add https://github.com/RbBtSn0w/gh-address-cr --skill gh-address-cr`. This installs the skill adapter and compatibility shim, not the Python package as an implementation owner.

README installation guidance must keep these surfaces separate so users do not confuse skill installation with runtime CLI installation.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reliable Local Installation (Priority: P1)

As an end user, I want to install the CLI in a clean environment without encountering missing runtime dependencies, so that it works reliably out of the box.

**Why this priority**: Missing dependencies make the installed CLI fail before it can emit structured machine output, blocking both human and AI-agent usage.

**Independent Test**: Build the package, install the built wheel into a clean virtual environment, and run installed CLI commands that cover both top-level and optional command groups.

**Acceptance Scenarios**:

1. **Given** a clean Python virtual environment, **When** the built wheel is installed, **Then** `gh-address-cr --help` exits successfully without dependency errors.
2. **Given** the same clean environment, **When** `gh-address-cr agent manifest` is run, **Then** it exits successfully and emits the runtime capability manifest.
3. **Given** the same clean environment and no existing PR session, **When** `gh-address-cr agent orchestrate status owner/repo 123` is run, **Then** the command must not fail with `ModuleNotFoundError` or a Python traceback; a structured session-state failure is acceptable.
4. **Given** the same clean environment, **When** `gh-address-cr final-gate owner/repo 123` is run without a session, **Then** the command must not fail with missing dependency import errors; a structured or documented missing-session failure is acceptable.

---

### User Story 2 - Automated CI Package Gates (Priority: P1)

As a maintainer, I want CI to build the package and prove the installed wheel works before merging, so that dependency and packaging regressions are caught before release.

**Why this priority**: Unit tests from the source tree do not catch missing package metadata, missing runtime dependencies, or broken console entrypoints.

**Independent Test**: Open a pull request and verify the CI package gate builds both wheel and sdist, installs the wheel in a clean environment, and runs installed CLI smoke commands.

**Acceptance Scenarios**:

1. **Given** a pull request, **When** CI runs, **Then** it must build both wheel and sdist artifacts.
2. **Given** the built wheel from CI, **When** it is installed in an isolated environment, **Then** the installed `gh-address-cr` executable must run the required smoke commands without import errors or tracebacks.
3. **Given** a CI package gate failure, **When** maintainers review the failure, **Then** the logs must identify which stage failed: build, install, or installed CLI smoke.

---

### User Story 3 - Automated PyPI Publishing (Priority: P1)

As a maintainer, I want semantic releases to publish the runtime CLI package to PyPI through Trusted Publishing, so that users can install the latest stable CLI from a standard registry.

**Why this priority**: Manual publishing is error-prone and undermines the CLI as a stable control-plane interface.

**Independent Test**: Run the release workflow in a dry-run or TestPyPI/staging mode before enabling production publishing; verify artifacts are built and the publishing step is correctly gated by PyPI Trusted Publishing configuration.

**Acceptance Scenarios**:

1. **Given** a semantic-release version is created on `main`, **When** the release workflow runs, **Then** the package build job must produce wheel and sdist artifacts before any publish step.
2. **Given** PyPI Trusted Publishing is configured for the repository workflow, **When** a production release is eligible, **Then** the workflow publishes the built artifacts to PyPI without requiring long-lived PyPI API tokens.
3. **Given** Trusted Publishing is not configured, package name ownership is not verified, or package build validation fails, **When** the release workflow reaches publish preparation, **Then** publishing must stop before uploading artifacts.
4. **Given** a publish attempt partially fails, **When** maintainers recover, **Then** the documented recovery path must require inspecting PyPI state and release artifacts before retrying or cutting a follow-up semantic release.

---

### User Story 4 - Clear Installation Documentation (Priority: P2)

As a new user, I want clear installation instructions for the runtime CLI, GitHub-direct validation, local development, and skill installation, so that I can choose the correct path without reading implementation details.

**Why this priority**: The repository now contains both a runtime CLI and a packaged skill; unclear installation docs can cause users to install only the skill and expect the runtime to exist.

**Independent Test**: Follow the README commands verbatim for `pipx`, `uv tool`, GitHub-direct install, local editable install, and skill install; each path must state its intended audience and post-install smoke command.

**Acceptance Scenarios**:

1. **Given** the README installation section, **When** a user wants the released CLI, **Then** they can copy either `pipx install gh-address-cr` or `uv tool install gh-address-cr`.
2. **Given** the README installation section, **When** a maintainer wants to validate unreleased code, **Then** they can find a GitHub-direct install path and a local editable development path.
3. **Given** the README installation section, **When** an AI-agent user wants the packaged skill, **Then** they can find the skills installer command and understand that it does not replace the runtime package.
4. **Given** a user previously relied on the packaged skill compatibility shim, **When** they need the released runtime CLI, **Then** the README explains the upgrade or reinstall path using `pipx` or `uv tool` without implying that reinstalling the skill installs the runtime package.

## Edge Cases

- The `gh-address-cr` name is unavailable on PyPI.
- PyPI Trusted Publishing is not configured or is configured for the wrong repository, workflow, environment, or package name.
- The package builds from source but the installed wheel misses runtime dependencies.
- CI can build artifacts but the installed executable fails with a Python traceback.
- GitHub Releases are produced by semantic-release before or without a successful PyPI publish.
- Semantic-release creates a version/tag, but the built wheel or sdist metadata still uses a stale package version.
- Users run the CLI with Python versions older than the supported `>=3.10` range.
- Users confuse `npx skills add ... --skill gh-address-cr` with the runtime CLI install.
- Users move from packaged skill or compatibility-shim usage to the installed runtime CLI and need clear upgrade or reinstall guidance.
- A PyPI publish partially succeeds and cannot be overwritten because package files are immutable.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The `pyproject.toml` MUST declare every runtime dependency needed by installed CLI command groups, including `packaging`.
- **FR-002**: CI MUST include a package gate with three distinct stages: build wheel/sdist, install the built wheel into a clean environment, and run installed CLI smoke commands.
- **FR-003**: Installed CLI smoke commands MUST include `gh-address-cr --help`, `python -m gh_address_cr --help`, `gh-address-cr agent manifest`, `gh-address-cr agent orchestrate status owner/repo 123`, and `gh-address-cr final-gate owner/repo 123`.
- **FR-004**: The clean-install smoke gate MUST treat missing imports, Python tracebacks, and missing console entrypoints as failures. Domain-state failures are acceptable only when they are emitted through documented CLI output.
- **FR-005**: The release workflow MUST build wheel and sdist artifacts before publishing and must publish the runtime CLI package to PyPI through PyPI Trusted Publishing.
- **FR-006**: PyPI package-name availability or ownership for `gh-address-cr` MUST be verified before enabling production publishing. If unavailable, implementation MUST stop for a naming decision.
- **FR-007**: PyPI MUST be the only documented stable package registry for released runtime CLI installation. GitHub Releases may remain release-note/source-archive surfaces, but must not be presented as the primary package registry.
- **FR-008**: Release documentation or workflow comments MUST document the required Trusted Publishing setup: PyPI project, repository, workflow file, optional environment, and publish permissions.
- **FR-009**: The release process MUST define a fail-fast recovery policy for failed or partially completed publishes, including manual PyPI state inspection before retrying.
- **FR-010**: The README MUST provide separate install sections for released CLI install, GitHub-direct validation install, local editable development install, and packaged skill install.
- **FR-011**: README install instructions MUST include `pipx install gh-address-cr`, `uv tool install gh-address-cr`, post-install smoke commands, and Python `>=3.10` expectations.
- **FR-012**: The implementation tasks MUST trace every edge case that affects release readiness to at least one task or explicit out-of-scope note.
- **FR-013**: The release workflow MUST synchronize the Python package version with the semantic-release version before building wheel/sdist artifacts and MUST fail before publishing if built artifact metadata does not match the release version.
- **FR-014**: README installation documentation MUST include upgrade or reinstall guidance for users moving from packaged skill or compatibility-shim usage to the installed runtime CLI.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: No direct mutation of runtime session state or GitHub IO behavior.
- **CLI / Agent Contract Impact**: Ensures the CLI can be reliably invoked by humans, scripts, and AI agents from an installed package.
- **Evidence Requirements**: Packaging work does not alter evidence semantics, but CI logs become release evidence.
- **Packaged Skill Boundary**: Runtime CLI packaging is owned by repo-root package metadata and workflows. Packaged skill installation remains a separate adapter install path and does not become the runtime implementation owner.
- **External Intake Replaceability**: No change.
- **Fail-Fast Behavior**: Build, install, smoke, package-name verification, and Trusted Publishing checks must stop release before a broken or ambiguous package is published.

### Key Entities

- **Runtime CLI Package**: The Python package named `gh-address-cr`, installed from PyPI and exposing the `gh-address-cr` executable.
- **Packaged Skill**: The `gh-address-cr/` directory installed through the skills installer; it routes agents to the runtime and compatibility shim.
- **Package Artifacts**: The generated wheel and sdist files.
- **Package Gate**: The CI build/install/installed-smoke sequence.
- **Release Workflow**: The GitHub Actions workflow that coordinates semantic-release and PyPI publishing.
- **Trusted Publishing Configuration**: The PyPI OIDC binding for repository, workflow, environment, and project name.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A fresh isolated install of the built wheel can execute all required smoke commands without missing dependency errors, Python tracebacks, or missing entrypoints.
- **SC-002**: CI reports build, install, and installed-smoke stages separately for every pull request.
- **SC-003**: A release workflow can build wheel/sdist artifacts and reach a PyPI Trusted Publishing dry-run or staging validation step without requiring a long-lived PyPI token.
- **SC-004**: README contains four distinct install paths: released CLI via `pipx`, released CLI via `uv tool`, GitHub-direct validation install, and local editable development install.
- **SC-005**: README keeps runtime CLI installation and packaged skill installation separate and gives a post-install smoke command for each relevant path.
- **SC-006**: Release-built wheel and sdist artifacts report a package version that matches the semantic-release version or tag for that release.
- **SC-007**: A user moving from skill-shim usage can identify the correct `pipx` or `uv tool` runtime CLI install or reinstall command without reinstalling the packaged skill as a substitute.

## Assumptions

- The project continues using semantic-release on `main` for version and release-note automation.
- The semantic-release version is the authoritative release version; implementation may either write it into package metadata before build or derive it dynamically from the release tag, but publishing must validate the resulting artifact version.
- PyPI Trusted Publishing is available for the target repository and package owner account.
- `gh-address-cr` is the preferred package name unless PyPI availability/ownership verification proves otherwise.
- Users installing the released CLI have Python `>=3.10` available through `pipx`, `uv`, or another isolated tool environment.
- Source archives created by GitHub are acceptable release-adjacent artifacts, but PyPI remains the only stable package registry for released CLI installs.
