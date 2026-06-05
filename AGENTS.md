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
- Preserve or explicitly version public CLI, machine-readable, and packaged-skill contracts when changing behavior.
- Remove deprecated or legacy compatibility paths only when the replacement contract is documented, tested, and versioned as public behavior, or when direct instructions explicitly require removal.
- Prefer a clean current contract over hidden shims, aliases, or fallback branches kept only for historical behavior.

### CLI and Skill Evolution Policy
- Treat this CLI as local-first tooling while keeping public CLI and machine-readable contracts stable or explicitly versioned.
- Treat the published `skill/` payload with the same standard: current guidance may evolve, but public agent-facing behavior must remain documented and tested.
- Do not spend maintenance effort on hidden historical compatibility unless a preserved or versioned public contract requires it.
- When CLI or skill behavior is modernized, update obsolete flags, pathways, references, and compatibility glue in the same documented contract change.

### Python Environment
- **Version**: Python 3.10+ (enforced by `pyproject.toml`).
- **Install for dev**: `pip install -e .`

### Testable Contracts And Fail-Fast Changes
Public behavior changes MUST update code, docs, and executable tests together. The project MUST fail fast on missing tools, malformed producer output, invalid handoff formats, unsafe resolve-only handling, and unsupported public command usage. Silent fallbacks, hidden compatibility shims, alternate prompt contracts, and narrative-only findings ingestion are forbidden unless they are explicitly documented, tested, and versioned as public behavior.

### Verification Commands
Before claiming work is complete, run these local checks:
- **Linting**: `ruff check src tests scripts/build_plugin_payload.py` (configured in `pyproject.toml`).
- **Unit Tests**: `python3 -m unittest discover -s tests`.
- **CLI Smoke Test**: `python3 -m gh_address_cr --help`.
- **Agent Contract Smoke Test**: `python3 -m gh_address_cr agent manifest`.
- **Plugin Payload Checks**: `python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr` and `python3 scripts/build_plugin_payload.py --check`.

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
- **Skill/runtime feedback**: When the `gh-address-cr` workflow itself blocks progress because of a repeatable skill/runtime gap, use `python3 -m gh_address_cr submit-feedback ...` against this repository instead of burying the problem in PR findings or local notes.

### Architecture Preflight Gate

Before editing implementation code, complete an Architecture Preflight when a
change touches runtime state, telemetry, final-gate behavior, leases, artifacts,
GitHub reply/resolve/publish side effects, session persistence,
Status-to-Action Map behavior, or structured agent protocol files. The
preflight must identify:

- authoritative state owner
- external facts or event inputs
- projection or derived-state shape
- policy table, status-to-action map, or deterministic decision function
- side-effect command plan or outbox boundary
- artifact truth boundary and telemetry/reporting self-reference risks
- recovery, replay, and executable contract tests

If review or implementation feedback repeatedly adds edge branches in the same
design axis without reducing the state space, stop expanding conditionals and
create or update an architecture spec instead. Local bug fixes are acceptable
only when they reduce ambiguity or remove a branch; they must not introduce
unmodeled state flags, hidden fallback paths, or artifact-backed truth.

## Completion Standard

A task is complete only when:
- The requested change is implemented and verified.
- The relevant contract docs remain consistent.
- `final-gate` passes (for PR-session handling work).
- PR-session completion evidence includes the `final-gate` compact metrics line
  (`completion_summary_line` or `PR Completion Summary Guidance`) with telemetry
  coverage and report artifacts; telemetry diagnostics are fail-open for review
  completion but must remain visible.
- No unresolved high-severity issues were introduced.

---
### Extracted Architectural Rules for Constitution
- Repository Identity (Resolution plane vs Review engine) -> Moved to Principle VII.
- Session state and Side-effect ownership -> Moved to Principle I.
- CLI as the stable public interface -> Moved to Principle II.
- Evidence-first handling (classification, classification reply/resolve) -> Moved to Principle III.
- Packaged skill boundary vs Deterministic Runtime -> Moved to Principle IV.
- Findings normalization and replaceability -> Moved to Principle VII.
- Telemetry attribution, coverage, and fail-open boundaries -> Moved to Principle VIII.

### Enhancements Made to AGENTS.md
- Added explicit pointer to `constitution.md`.
- Explicitly defined Python 3.10+ and `src/` layout requirements.
- Consolidated verification commands to match `pyproject.toml`.
- Added Conventional Commits guideline.
- Simplified "Execution Discipline" to focus on repository-root behavior.
- Added explicit public-contract preservation and versioning guidance for feature updates.
- Added local-first CLI and skill evolution guidance for documented compatibility cleanup.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
  [specs/018-runtime-kernel/plan.md](specs/018-runtime-kernel/plan.md)
<!-- SPECKIT END -->
