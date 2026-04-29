# Research: CLI Distribution Packaging & Publishing

## PyPI Publishing via GitHub Actions

**Decision**: Use PyPI Trusted Publishing (OIDC) with `pypa/gh-action-pypi-publish`.
**Rationale**: It is the modern, secure standard for publishing Python packages from GitHub Actions. It eliminates the need for long-lived API tokens stored in GitHub Secrets.
**Alternatives considered**: Traditional PyPI API tokens (less secure, requires manual rotation).

## Package Name Verification

**Decision**: Continue using `gh-address-cr` as the preferred PyPI project name.
**Evidence**: On 2026-04-29, an exact PyPI project search for `gh-address-cr` did not return an existing project result. Production publishing still requires creating or controlling the PyPI project and configuring Trusted Publishing before the `pypi` target is enabled.
**Failure handling**: If PyPI rejects the project name or ownership cannot be verified, production publishing must stop for a naming decision before any upload attempt.

## Protected Publishing Environment

**Decision**: Use a protected GitHub environment named `pypi` for production PyPI publishing.
**Rationale**: Production package uploads are irreversible for a given version. The environment gives maintainers a review/approval boundary while preserving Trusted Publishing through OIDC.
**Scope**: The `testpypi` and `dry-run` validation paths do not use the `pypi` environment because they must be usable before production publishing is enabled.

## Installed Smoke Contract

**Decision**: The installed CLI smoke gate runs `gh-address-cr --help`, `python -m gh_address_cr --help`, `gh-address-cr agent manifest`, `gh-address-cr agent orchestrate status owner/repo 123`, and `gh-address-cr final-gate owner/repo 123`.
**Rationale**: The command set covers top-level entrypoints, module entrypoint, agent manifest import path, orchestration command group, and final-gate command group.
**Accepted failures**: Missing sessions or domain-state failures are acceptable only when they are emitted as structured/documented CLI output, including structured `status`/`reason_code` payloads and the documented `Final gate failed to evaluate: error connecting to api.github.com` external GitHub failure. `ModuleNotFoundError`, missing console entrypoints, Python tracebacks, or command-not-found failures are release blockers.

## Package Version Synchronization

**Decision**: Keep semantic-release as the release authority and use `scripts/set_package_version.py` during semantic-release prepare to write the release version into `pyproject.toml` and `src/gh_address_cr/__init__.py`.
**Rationale**: PyPI package filenames are immutable, so every production upload must carry the exact semantic-release version before wheel/sdist artifacts are built.
**Validation**: The release workflow verifies the wheel and sdist metadata version after build and fails before publishing if either artifact does not match the release version.

## Dry-Run and Staging Publishing

**Decision**: Add `workflow_dispatch` with `dry-run`, `testpypi`, and `pypi` targets.
**Rationale**: Maintainers need a package-build validation path and a Trusted Publishing staging path before enabling production PyPI publishing.
**Semantics**: `dry-run` builds and verifies artifacts without uploading. `testpypi` builds, verifies, and publishes to TestPyPI via OIDC. `pypi` requires explicit confirmation and the protected `pypi` environment.

## Smoke Testing During CI

**Decision**: Add a step to the main CI workflow (or a new job) that builds the wheel and sdist using the `build` module, installs it into an isolated venv, and runs `gh-address-cr --help` or `python -m gh_address_cr --help`.
**Rationale**: This guarantees that `pyproject.toml`'s `dependencies` are complete and correct before any release tag is even created or published.
**Alternatives considered**: Only testing via pytest (this doesn't catch packaging/dependency omission issues like `ModuleNotFoundError`).

## End-User Installation Tools

**Decision**: Officially document `pipx` and `uv tool`.
**Rationale**: Installing global CLI tools via standard `pip install` risks breaking system environments or causing dependency conflicts. Both `pipx` and `uv` isolate the CLI tool into its own environment while exposing the executable, which is the recommended Python packaging best practice for CLIs.
**Alternatives considered**: Standard `pip install` (not recommended for CLI tools).
