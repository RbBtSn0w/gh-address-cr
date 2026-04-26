# AGENTS.md

> **Note:** For project-specific architectural rules, design patterns, and coding standards, refer to `.specify/memory/constitution.md`. This file owns the day-to-day agent execution rules and infrastructure guidelines for this source repository.

## Repository Model

This repository has two different scopes. Do not blur them:

- **Repository root**: Development, verification, CI, release metadata, and contributor guidance.
- **`gh-address-cr/`**: The installable and published skill folder.

The released skill payload is the entire `gh-address-cr/` directory. Files such as `tests/`, `.github/`, `pyproject.toml`, `README.md`, and this `AGENTS.md` support development and release, but are not part of the installed skill.

## Scope and Authority

Follow this order of precedence:
1. Direct system, developer, and user instructions.
2. `.specify/memory/constitution.md` (Architecture & Governance).
3. This `AGENTS.md` (Infrastructure & Execution).
4. Executable repository contracts in `tests/`.

## Infrastructure Guidelines

### Python Environment
- **Version**: Python 3.10+ (enforced by `pyproject.toml`).
- **Layout**: Source code lives in `src/gh_address_cr/`.
- **Install for dev**: `pip install -e .`

### Verification Commands
Before claiming work is complete, run these local checks:
- **Linting**: `ruff check src tests` (configured in `pyproject.toml`).
- **Unit Tests**: `python3 -m unittest discover -s tests`.
- **CLI Smoke Test**: `python3 -m gh_address_cr --help` or `python3 gh-address-cr/scripts/cli.py --help`.

### Git Workflow
- **Status Check**: Always run `git status` before starting work.
- **Commit Format**: Use Conventional Commits (e.g., `feat:`, `fix:`, `docs:`, `refactor:`).
- **History**: Propose a draft commit message. Do not stage/commit unless explicitly requested.

## Path Conventions

- **In repo-root docs/tests**: Use repo-root paths like `gh-address-cr/scripts/cli.py`.
- **In skill-owned docs (`gh-address-cr/`)**: Use skill-root-relative paths like `scripts/cli.py`.

## Execution Discipline

- **Read first**: Read relevant contracts in `README.md` or `constitution.md` before editing.
- **Verify first**: Confirm current behavior or reproduce bugs before proposing fixes.
- **Fail fast**: Do not add silent fallbacks or hidden behavior changes.
- **Smallest change**: Default to the smallest safe change. Avoid opportunistic refactors.
- **Contract discipline**: If a public or agent-facing contract changes, update docs and tests together.

## Completion Standard

A task is complete only when:
- The requested change is implemented and verified.
- The relevant contract docs remain consistent.
- `final-gate` passes (for PR-session handling work).
- No unresolved high-severity issues were introduced.

---
### Extracted Architectural Rules for Constitution
- Repository Identity (Resolution plane vs Review engine) -> Moved to Principle VII.
- Session state and Side-effect ownership -> Moved to Principle I.
- CLI as the stable public interface -> Moved to Principle II.
- Evidence-first handling (classification, classification reply/resolve) -> Moved to Principle III.
- Packaged skill boundary vs Deterministic Runtime -> Moved to Principle IV.
- Findings normalization and replaceability -> Moved to Principle VII.

### Enhancements Made to AGENTS.md
- Added explicit pointer to `constitution.md`.
- Explicitly defined Python 3.10+ and `src/` layout requirements.
- Consolidated verification commands to match `pyproject.toml`.
- Added Conventional Commits guideline.
- Simplified "Execution Discipline" to focus on repository-root behavior.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read
`specs/004-agent-orchestrator-mvp/plan.md`.
<!-- SPECKIT END -->