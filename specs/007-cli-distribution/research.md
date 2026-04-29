# Research: CLI Distribution Packaging & Publishing

## PyPI Publishing via GitHub Actions

**Decision**: Use PyPI Trusted Publishing (OIDC) with `pypa/gh-action-pypi-publish`.
**Rationale**: It is the modern, secure standard for publishing Python packages from GitHub Actions. It eliminates the need for long-lived API tokens stored in GitHub Secrets.
**Alternatives considered**: Traditional PyPI API tokens (less secure, requires manual rotation).

## Smoke Testing During CI

**Decision**: Add a step to the main CI workflow (or a new job) that builds the wheel and sdist using the `build` module, installs it into an isolated venv, and runs `gh-address-cr --help` or `python -m gh_address_cr --help`.
**Rationale**: This guarantees that `pyproject.toml`'s `dependencies` are complete and correct before any release tag is even created or published.
**Alternatives considered**: Only testing via pytest (this doesn't catch packaging/dependency omission issues like `ModuleNotFoundError`).

## End-User Installation Tools

**Decision**: Officially document `pipx` and `uv tool`.
**Rationale**: Installing global CLI tools via standard `pip install` risks breaking system environments or causing dependency conflicts. Both `pipx` and `uv` isolate the CLI tool into its own environment while exposing the executable, which is the recommended Python packaging best practice for CLIs.
**Alternatives considered**: Standard `pip install` (not recommended for CLI tools).
