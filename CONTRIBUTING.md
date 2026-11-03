# Contributing to gh-address-cr

We welcome contributions! Please follow these guidelines:

## How to Contribute

1.  **Fork the Repository**: Create a fork of this repository on GitHub.
2.  **Create a Feature Branch**: Make your changes in a dedicated branch (`git checkout -b feature/my-feature`).
3.  **Run Checks**: Follow the development checks in `README.md`. Use the offline fake-GitHub contracts for regression tests; packaging changes also run the installed-wheel smoke and agent journey in a fresh environment.
4.  **Dogfood Runtime Changes**: To try an unreleased runtime on a real PR, pin it with `scripts/dogfood_env.sh` (see "Dogfooding an unreleased runtime" in `README.md`).
5.  **Submit a Pull Request**: Provide a clear description of your changes and why they are needed.

## Standards

-   **Shell Scripts**: Use `set -euo pipefail` for robustness. Follow `shellcheck` recommendations.
-   **Documentation**: Keep `SKILL.md` and `README.md` up to date with any changes to the core protocol or script usage.
-   **Templates**: If you add new reply templates, ensure they follow the evidence-first principles.
-   **Multi-process tests**: Runtime-store contract tests that need real cross-process contention use `multiprocessing.get_context("spawn")`, never `fork`. Forking a process that already used SQLite can crash the child with SIGSEGV (exit code -11) when Python links the macOS system SQLite, which pyenv builds on macOS often do by default (Homebrew Python links Homebrew SQLite); linkage varies by build options, so the safe rule is to avoid fork-after-SQLite. Keep worker targets module-level and their arguments picklable.
-   **Commits (required for automated release)**: Use Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, etc.).

## Release Process

Task PRs target `main`. Friday 07:00 UTC and manual dispatch share read-only
verification and dependent publishers; `RELEASE_ENABLED` defaults off. See
[Main release train](docs/release/main-train.md) for version selection, immutable
artifact handoff, publication authority, activation and partial recovery.

PyPI uses Trusted Publishing. Homebrew preserves its four-platform verification
and existing tap App credentials. Marketplace retains version-only recovery from
verified release assets. No version/changelog commit or PR preview is produced.

## Security

-   Never commit personal access tokens or sensitive information to the repository.
-   Use `.env.example` as a template for local environment variables.
