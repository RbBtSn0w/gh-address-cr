# Contributing to gh-address-cr-skill

We welcome contributions! Please follow these guidelines:

## How to Contribute

1.  **Fork the Repository**: Create a fork of this repository on GitHub.
2.  **Create a Feature Branch**: Make your changes in a dedicated branch (`git checkout -b feature/my-feature`).
3.  **Run Tests**: Ensure your changes don't break existing functionality. Since these are shell scripts, you can test them locally with a test PR.
4.  **Submit a Pull Request**: Provide a clear description of your changes and why they are needed.

## Standards

-   **Shell Scripts**: Use `set -euo pipefail` for robustness. Follow `shellcheck` recommendations.
-   **Documentation**: Keep `SKILL.md` and `README.md` up to date with any changes to the core protocol or script usage.
-   **Templates**: If you add new reply templates, ensure they follow the evidence-first principles.
-   **Commits (required for automated release)**: Use Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, etc.).

## Release Process

-   CI runs `semantic-release` on pushes to `main`.
-   Releases are inferred from commit history:
    -   `fix:` => patch
    -   `feat:` => minor
    -   `BREAKING CHANGE:` or `feat!:` / `fix!:` => major
-   The workflow publishes:
    -   Git tag (`vX.Y.Z`)
    -   GitHub Release
    -   `CHANGELOG.md` update committed back to `main`

## Security

-   Never commit personal access tokens or sensitive information to the repository.
-   Use `.env.example` as a template for local environment variables.
