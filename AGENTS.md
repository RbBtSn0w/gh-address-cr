# AGENTS.md

> **Note:** For project-specific architectural rules, design patterns, and coding standards, refer to `.specify/memory/constitution.md`. This file owns the day-to-day agent execution rules and infrastructure guidelines for this source repository.

## Repository Model

This repository has two different scopes. Do not blur them:

- **Repository root**: Development, verification, CI, release metadata, and contributor guidance.
- **`skill/`**: The installable and published skill folder.

The released skill payload is the entire `skill/` directory. Files such as `tests/`, `.github/`, `pyproject.toml`, `README.md`, and this `AGENTS.md` support development and release, but are not part of the installed skill.

The payload directory name is `skill/`, but the product/runtime identity remains
`gh-address-cr`: the Python package, console entrypoint, repository URL,
`SKILL.md` frontmatter `name`, and `/gh-address-cr` invocation must not be
renamed to `skill`. Skills installer examples should select the payload folder
with `--skill skill`.

## Scope and Authority

Follow this order of precedence:
1. Direct system, developer, and user instructions.
2. `.specify/memory/constitution.md` (Architecture & Governance).
3. This `AGENTS.md` (Infrastructure & Execution).
4. Executable repository contracts in `tests/`.

## Infrastructure Guidelines

### Compatibility Policy
- Default to current best-practice behavior. Do not preserve backward compatibility unless explicitly requested by direct instructions.
- Remove deprecated or legacy compatibility paths when updating features.
- Prefer a clean contract over transitional shims, aliases, or fallback branches kept only for historical behavior.

### CLI And Skill Evolution Policy
- Treat this CLI as local-first tooling and optimize for the best current usage patterns.
- Treat the published `skill/` payload with the same standard: prioritize current best-practice behavior over legacy compatibility.
- Do not spend maintenance effort on historical CLI or skill compatibility unless explicitly required.
- When CLI or skill behavior is modernized, remove obsolete flags, pathways, references, and compatibility glue in the same change.

### Python Environment
- **Version**: Python 3.10+ (enforced by `pyproject.toml`).
- **Install for dev**: `pip install -e .`

### Testable Contracts And Fail-Fast Changes
Public behavior changes MUST update code, docs, and executable tests together. The project MUST fail fast on missing tools, malformed producer output, invalid handoff formats, unsafe resolve-only handling, and unsupported public command usage. Silent fallbacks, hidden compatibility shims, alternate prompt contracts, and narrative-only findings ingestion are forbidden unless they are explicitly documented, tested, and versioned as public behavior.

### Verification Commands
Before claiming work is complete, run these local checks:
- **Linting**: `ruff check src tests` (configured in `pyproject.toml`).
- **Unit Tests**: `python3 -m unittest discover -s tests`.
- **CLI Smoke Test**: `python3 -m gh_address_cr --help`.

### Git Workflow
- **Status Check**: Always run `git status` before starting work.
- **Commit Format**: Use Conventional Commits (e.g., `feat:`, `fix:`, `docs:`, `refactor:`).
- **History**: Propose a draft commit message. Do not stage/commit unless explicitly requested.

## Path Conventions

- **In repo-root docs/tests**: Use repo-root paths like `src/gh_address_cr/cli.py`.
- **In skill-owned docs (`skill/`)**: Use skill-root-relative paths like `references/...` and `agents/openai.yaml`.
- **Do not rename product identifiers**: Use `gh-address-cr` for the runtime CLI, PyPI package, GitHub repository, skill name, and slash command.

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
- Added explicit no-backward-compatibility default for feature updates.
- Added local-first CLI and skill evolution guidance to remove obsolete compatibility paths.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
  [specs/014-fix-all-thread-replies/plan.md](specs/014-fix-all-thread-replies/plan.md)
<!-- SPECKIT END -->
