# AGENTS.md

This file is the repository-level constitution for agents working in the source repo.
It is not itself part of the packaged skill payload.
Read it first to understand the repo layout, release boundary, and completion standard.

## Scope And Authority

Follow this order of precedence:

1. Direct system, developer, and user instructions
2. This `AGENTS.md`
3. Executable repository contracts in `tests/`
4. Public product and skill contracts in `README.md`

If a lower-level doc conflicts with a higher-level instruction, follow the higher-level instruction and do not silently blend them.

## Repository Model

This repository has two different scopes. Do not blur them:

- Repository root: development, verification, CI, release metadata, and contributor guidance
- `gh-address-cr/`: the installable and published skill folder

The released skill payload is the entire `gh-address-cr/` directory.
Repo-root files such as `tests/`, `.github/`, `pyproject.toml`, `README.md`, `CHANGELOG.md`, and this `AGENTS.md` support development and release, but are not the installed skill payload.

If a rule must survive packaging and be visible inside the installed skill, it must live under `gh-address-cr/`, primarily in `gh-address-cr/SKILL.md` and other skill-owned files.

## Repository Identity

`gh-address-cr-skill` is a PR-scoped workflow orchestrator for AI coding agents.
It is not the review engine itself.

Preserve these core truths:

- The repository owns session state, intake routing, reply/resolve discipline, and final gating.
- The public main entrypoint is `review`.
- High-level CLI commands are the only agent-safe public surface.
- Low-level scripts are implementation details unless a task explicitly requires them.
- External review producers are replaceable; the normalized findings contract is the stable boundary.

## Source Of Truth Map

Start from the smallest document that governs the task:

- `README.md`: repo-level product behavior, release, and install guidance
- `tests/`: repo-level executable verification contracts
- `gh-address-cr/`: the shipped skill root and only packaged skill payload

Interpret `gh-address-cr/` this way:

- `gh-address-cr/SKILL.md`: the skill contract and first-read agent entrypoint after packaging
- `gh-address-cr/scripts/`: skill-owned implementation and CLI surfaces
- `gh-address-cr/references/`: advanced reference material shipped with the skill
- `gh-address-cr/assets/`: packaged templates and other skill assets
- `gh-address-cr/agents/`: assistant-specific hint files layered on top of the core skill

Do not redesign this structure casually. Changes under `gh-address-cr/` should preserve the fact that the folder is a distributable skill with its own canonical layout.

## Path Conventions

Use path language that matches the scope you are talking about:

- In repo-level docs, tests, and shell commands from repository root, use repo-root paths such as `gh-address-cr/scripts/cli.py`.
- In skill-owned docs inside `gh-address-cr/`, use skill-root-relative paths such as `scripts/cli.py`, `references/...`, and `agents/openai.yaml`.

Do not mix these two perspectives in the same explanation without making the scope explicit.


## Default Working Rules

For any non-trivial task:

1. Read the relevant contract before editing code or docs.
2. Verify the current behavior in code, tests, or runtime output before proposing a fix.
3. Prefer the highest-level supported entrypoint over internal scripts.
4. Keep changes local to the confirmed issue. Avoid opportunistic refactors.
5. Update docs and tests together when a public or agent-facing contract changes.

## Non-Negotiable Engineering Rules

- Fail fast. Do not add silent fallbacks, vague compatibility shims, or hidden behavior changes.
- Evidence first. Do not claim a bug, regression, or fix without code, test, or command evidence.
- Public interface first. Prefer the high-level CLI over composing internal scripts by hand.
- At repo root, repo-executable commands use paths like `python3 gh-address-cr/scripts/cli.py ...`.
- Inside skill-owned docs, the same entrypoints should be written relative to the skill root as `python3 scripts/cli.py ...`.
- Contract discipline matters more than convenience. Do not invent alternate prompt templates or weaker ingestion formats.
- `review-to-findings` only accepts fixed `finding` blocks, not arbitrary narrative Markdown.
- GitHub thread handling requires both reply and resolve. One without the other is incomplete.
- Local findings must end with an explicit terminal handling note.
- If a review item is unclear, classify it before changing code: `fix`, `clarify`, `defer`, or `reject`.
- If the issue is real but out of scope, defer it with rationale instead of stretching the current change.

## Documentation Rules

This repository ships a skill, so documentation is part of the product surface.

- Keep public semantics aligned across `README.md`, `gh-address-cr/SKILL.md`, and tests.
- Keep the repo-vs-skill boundary explicit in prose. Do not write as if repo root and skill root are the same directory.
- When editing skill-owned docs under `gh-address-cr/`, use paths relative to the skill root inside those docs.
- Do not duplicate multiple prompt templates with weaker wording when one canonical contract is intended.
- If a behavior change affects examples, update the examples in the same change.

## Editing Boundaries

Default to the smallest safe change.

- Do not rename public commands, machine summary fields, or stable file contracts without updating docs and tests together.
- Do not bypass the normalized findings contract just because one producer emits a different shape.
- Do not turn internal implementation details into new public interfaces casually.
- Do not revert unrelated user changes.

## Verification Requirements

Before claiming repository work is complete, run the smallest verification that matches the change.

For code changes, prefer running the current CI-equivalent checks locally before completion claims.
At the time of writing, `.github/workflows/ci.yml` runs:

- `ruff check gh-address-cr tests`
- `python3 -m unittest discover -s tests`

If your change touches a surface that CI also smoke-tests, run the matching local command as well instead of stopping at unit tests.

Default repository verification:

- `python3 -m unittest discover -s tests`

For CLI-surface or packaging changes, also run:

- `python3 gh-address-cr/scripts/cli.py --help`

For changes that touch `cr-loop`, also run:

- `python3 gh-address-cr/scripts/cli.py cr-loop --help`

For actual PR-session handling work, completion claims are forbidden until:

- `python3 gh-address-cr/scripts/cli.py final-gate <owner/repo> <pr_number>` has just passed
- the output confirms `Verified: 0 Unresolved Threads found`
- session blocking item count is zero

If you did not run a relevant check, say so explicitly.

## Completion Standard

You may say a task is complete only when all of the following are true:

- the requested change is actually implemented or the blocker is explicitly stated
- the relevant contract docs remain consistent
- the appropriate verification for the scope has been run, or the gap is clearly disclosed
- no unresolved high-severity issue introduced by your change is being ignored

When in doubt, be precise, be explicit, and fail loudly rather than leaving the repository in an ambiguous state.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->
