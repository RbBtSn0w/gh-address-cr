# Implementation Plan: CLI Distribution Packaging & Publishing

**Branch**: `007-cli-distribution` | **Date**: 2026-04-29 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/007-cli-distribution/spec.md`

## Summary

This feature turns the existing runtime CLI skeleton into a distributable Python CLI package with explicit installation paths and release gates. The runtime CLI package is published through PyPI as `gh-address-cr`; the packaged skill remains installed separately through the skills installer and continues to act as a thin adapter. The implementation fixes missing runtime dependencies, adds build/install/installed-smoke CI gates, prepares PyPI Trusted Publishing, documents release recovery rules, and updates README installation paths for released CLI, GitHub-direct validation, local development, and packaged skill usage.

## Technical Context

**Language/Version**: Python 3.10+
**Runtime Dependencies**: Declared in `pyproject.toml`; known missing dependency is `packaging`
**Build Dependencies**: `setuptools`, `build`, and GitHub Actions tooling
**Publishing**: PyPI Trusted Publishing through `pypa/gh-action-pypi-publish`; production publishing must not use long-lived PyPI API tokens unless a separate release-policy change approves that fallback
**Release Automation**: Existing semantic-release workflow on `main` remains the version/release-notes authority; Python package artifacts must use the same version
**Storage**: N/A
**Testing**: `unittest`, `ruff`, package build, clean wheel install, installed CLI smoke
**Target Platform**: Python 3.10+ on Linux CI; user docs cover isolated installs via `pipx` and `uv tool`
**Project Type**: CLI application plus packaged skill adapter repository
**Performance Goals**: N/A
**Constraints**: Must install cleanly without missing imports, Python tracebacks, or broken console entrypoints
**Scale/Scope**: Repository-root packaging config, CI/release workflows, README installation docs, and package smoke tests

## Distribution Boundary

The implementation must preserve three separate user-facing install surfaces:

```text
Released runtime CLI:
  pipx install gh-address-cr
  uv tool install gh-address-cr

GitHub-direct runtime validation:
  pipx install git+https://github.com/RbBtSn0w/gh-address-cr.git
  uv tool install git+https://github.com/RbBtSn0w/gh-address-cr.git

Packaged skill adapter:
  npx skills add https://github.com/RbBtSn0w/gh-address-cr --skill gh-address-cr
```

The released runtime CLI is the implementation owner. The packaged skill is not a bundled replacement for the Python package; it routes agent behavior to the installed runtime or compatibility shim.

## Package Gate Design

CI must expose three separate gates so failures are diagnosable:

1. **Build gate**: build wheel and sdist from the repository checkout.
2. **Install gate**: install the built wheel into a clean virtual environment.
3. **Installed smoke gate**: run installed commands:
   - `gh-address-cr --help`
   - `python -m gh_address_cr --help`
   - `gh-address-cr agent manifest`
   - `gh-address-cr agent orchestrate status owner/repo 123`
   - `gh-address-cr final-gate owner/repo 123`

The smoke gate must fail on missing imports, tracebacks, missing console entrypoints, or missing runtime dependency errors. Missing-session or domain-state failures are acceptable only when they are structured/documented CLI results.

## Release Design

The release workflow keeps semantic-release as the source for version tags and GitHub release notes. PyPI is the only stable package registry for released runtime CLI installation.

### Package Version Synchronization

The Python package version must be synchronized before any release artifact is built. The accepted implementation may either:

- write the semantic-release `nextRelease.version` into package metadata before `python -m build`, or
- derive the package version dynamically from the release tag with a deterministic packaging tool.

The release workflow must validate the generated wheel and sdist metadata after build. If artifact metadata does not match the semantic-release version or tag being released, publishing must stop before any upload attempt.

GitHub Releases may still exist for:

- semantic-release notes
- git tags
- source archives automatically produced by GitHub
- optional provenance/build attestations

GitHub Releases must not be documented as the primary Python package registry and must not replace PyPI installation instructions.

Production PyPI publishing must use Trusted Publishing:

- PyPI project name: `gh-address-cr`
- GitHub repository: `RbBtSn0w/gh-address-cr`
- workflow file: `.github/workflows/release.yml`
- publish action: `pypa/gh-action-pypi-publish`
- permissions: `id-token: write` and appropriate repository read permissions
- optional GitHub environment: `pypi` if maintainers want manual approval

Before enabling production publishing, implementation must verify package-name availability or ownership. If `gh-address-cr` is unavailable and not controlled by the project owner, the implementation must stop for a naming decision.

### Dry-Run / Staging Validation

Before production publishing is enabled, the workflow must expose a dry-run or staging path. This may be a `workflow_dispatch` validation mode, TestPyPI publish, or equivalent Trusted Publishing staging check. The path must prove that artifacts build, credentials are resolved through OIDC, and production PyPI is not modified during validation.

## Failure Recovery Policy

Publishing failures must fail fast and require explicit state inspection:

- If build or install gates fail, no publish step may run.
- If Trusted Publishing is not configured, publish must fail before artifact upload.
- If package-name ownership is not verified, production publish must remain disabled.
- If the built artifact version does not match the semantic-release version, no publish step may run.
- If PyPI upload partially succeeds, maintainers must inspect the PyPI project state before retrying. Because PyPI files are immutable, recovery may require cutting a new semantic-release version rather than re-uploading the same artifact name.
- GitHub Release notes may exist even when PyPI publish fails; README and release notes must not claim the runtime CLI is installable from PyPI until upload success is verified.

## Constitution Check

*GATE: Must pass before implementation. Re-check after workflow/docs changes.*

- **Control plane ownership**: PASS. Packaging changes do not change runtime session state, GitHub IO, leases, evidence, or final-gate semantics.
- **Public CLI contract**: PASS. The feature hardens the existing `gh-address-cr` public CLI entrypoint and adds install validation for it.
- **Evidence-first handling**: PASS. Runtime evidence semantics are unchanged; CI logs and release artifacts become release-readiness evidence.
- **Packaged skill boundary**: PASS. Runtime package distribution and skill installation are documented as separate surfaces.
- **External intake replaceability**: PASS. No review producer or intake behavior changes.
- **Fail-fast verification**: PASS. Build, install, installed-smoke, package-name verification, and Trusted Publishing checks prevent broken release claims.

## Project Structure

### Documentation (this feature)

```text
specs/007-cli-distribution/
├── spec.md
├── plan.md
├── research.md
├── tasks.md
└── checklists/
    └── requirements.md
```

No `data-model.md` or `contracts/` are needed because this feature does not alter runtime data entities or agent-facing protocols.

### Source Code (repository root)

```text
.github/
└── workflows/
    ├── ci.yml           # add package build/install/installed-smoke gate
    └── release.yml      # build dist and publish to PyPI via Trusted Publishing

pyproject.toml           # add runtime dependencies and package metadata
README.md                # add separated installation paths and recovery notes
tests/
└── test_runtime_packaging.py  # extend package/manifest/installability checks if needed
```

**Structure Decision**: Keep package configuration and release engineering at repository root. Do not move implementation code into `gh-address-cr/`, and do not make the packaged skill own runtime state.

## Phase Plan

### Phase 0 - Readiness Fixes

- Verify `gh-address-cr` package-name availability or ownership on PyPI.
- Define the exact installed smoke command acceptance model.
- Define the package version synchronization mechanism for semantic-release and Python artifacts.
- Define the dry-run/TestPyPI/staging validation path and success criteria.
- Confirm whether the release workflow should use a `pypi` GitHub environment for manual approval.

### Phase 1 - Package Metadata & Dependency Closure

- Add missing runtime dependencies to `pyproject.toml`.
- Add package metadata needed for PyPI publication: README, license, authors/maintainers if available, classifiers, URLs.
- Verify the installed package carries required runtime modules and compatibility delegates.

### Phase 2 - CI Package Gate

- Add package build step.
- Install the built wheel into a clean environment.
- Run installed CLI smoke commands and fail on import errors, tracebacks, or missing entrypoints.

### Phase 3 - Release Workflow

- Build wheel and sdist before publish.
- Synchronize and validate the Python artifact version against semantic-release before publishing.
- Publish to PyPI using Trusted Publishing.
- Add dry-run/TestPyPI/staging validation before production publishing is enabled.
- Gate production publishing on package-name/ownership verification and successful package validation.
- Preserve semantic-release for tags and GitHub release notes.

### Phase 4 - Documentation

- Add README install section with released CLI via `pipx` and `uv tool`.
- Add GitHub-direct validation install.
- Add local editable development install.
- Keep packaged skill installation separate and explicit.
- Add upgrade or reinstall guidance for users moving from packaged skill or compatibility-shim usage to the released runtime CLI.
- Add post-install smoke commands and failure recovery notes.

### Phase 5 - Verification

- Run `ruff check src tests`.
- Run `python3 -m unittest discover -s tests`.
- Run local package build.
- Confirm built artifact metadata version matches the semantic-release version source used for the release validation.
- Install built wheel into a clean venv and run installed smoke commands.
- Run the dry-run/TestPyPI/staging publishing validation path before production publishing is enabled.
- Confirm README commands are copy-pasteable.
- Confirm migration/reinstall guidance does not present the packaged skill as a substitute for runtime CLI installation.

## Complexity Tracking

No constitution violations are expected. The main risk is release-process coupling: semantic-release creates GitHub tags/releases, while PyPI publishing is a Python packaging concern. The plan keeps semantic-release as the version/release-notes authority and adds PyPI publishing as a gated package step.
