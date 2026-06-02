# Architecture

## Runtime / Skill Split

The deterministic implementation belongs to the runtime package:

- console entrypoint: `gh-address-cr`
- module entrypoint: `python3 -m gh_address_cr`
- source package: `src/gh_address_cr/`

The packaged skill remains under `skill/` and acts as a thin adapter:

- `skill/SKILL.md` explains agent behavior
- `skill/runtime-requirements.json` declares runtime compatibility
- `skill/agents/` and `skill/references/` provide hints and reference docs

The runtime must be available or execution must fail loudly before mutating session state. Runtime state machines, leases, GitHub side effects, evidence ledgers, and final-gate behavior must not be reimplemented as skill-owned workflow code.


## PR Session Architecture

`gh-address-cr` ships the session engine inside the runtime package and exposes supported workflows through the public `gh-address-cr` entrypoint.

The implementation model is now:

- Python owns the stateful logic and GitHub/local-review orchestration.
- `gh-address-cr` is the only stable automation entrypoint for runtime work.
- Tests are organized around Python behavior first, then CLI syntax compatibility.

- `github_thread` items are synced from GraphQL thread snapshots.
- `local_finding` items are ingested from a local review adapter.
- local findings can be explicitly handled in-session with `gh-address-cr agent fix`, `gh-address-cr agent fix-all`, or `gh-address-cr submit-action`.
- `gh-address-cr final-gate` evaluates both:
  - session blocking item count
  - unresolved GitHub thread count
  - terminal GitHub thread reply-evidence count
  - current-login pending review count
  - optional PR checks when `--require-checks` or `--require-required-checks` is supplied

The session state is stored in a PR-scoped workspace under the user cache directory:

- workspace: `<owner>__<repo>/pr-<pr>/`
- session: `session.json`
- GitHub snapshots: `threads.jsonl`
- handled threads: `handled_threads.txt`
- audit log: `audit.jsonl`
- trace log: `trace.jsonl`
- audit summary: `audit_summary.md`
- findings: `findings-*.json` and `code-review-findings.json`
- replies: `reply-*.md`
- loop requests: `loop-request-*.json`
- validation records: `validation-*.json`

`session.json` owns command-to-command handoff state. In addition to local and
GitHub work items, `handoff.producer_results` records source-scoped producer
submissions so a later plain `review` command can continue the same PR session
after `findings --input <path>|- --source <producer>` succeeds, including
explicit empty `[]` results.

If `gh-address-cr final-gate --auto-clean` passes, the current PR workspace is archived before deletion under:

- archive root: `archive/<owner>__<repo>/pr-<pr>/<run_id>/`

To inspect one run after the fact, use:

```bash
gh-address-cr final-gate --no-auto-clean <owner/repo> <pr_number>
```

The session also tracks loop-safety metadata per item:

- `repeat_count`: how many times the same local finding was re-ingested
- `reopen_count`: how many times a previously closed/deferred/clarified item was reopened
- claim lease fields so stale ownership can be reclaimed


## Runtime Package Layout

The main logic lives in the Python runtime package under `src/gh_address_cr/`.

- `cli.py`: console entrypoint and runtime command dispatch
- `core/`: session state, workflow transitions, final-gate, and orchestration helpers
- `github/`: GitHub CLI IO and failure diagnostics
- `intake/`: findings parsing and normalization
- `legacy_handlers/`: helper implementations that remain behind supported public commands

New automation should use `gh-address-cr`, not direct script paths.

The runtime package requires Python 3.10+ because the implementation uses modern typing syntax such as `list[str]` and `str | None`.

The `gh-address-cr` console script is the stable automation surface.

Unified CLI examples:

```bash
gh-address-cr review owner/repo 123
gh-address-cr address owner/repo 123 --lean
gh-address-cr final-gate --no-auto-clean owner/repo 123
gh-address-cr review owner/repo 123 --input -
gh-address-cr findings owner/repo 123 --input -
gh-address-cr agent fix owner/repo 123 local-finding:<fingerprint> --commit <sha> --files src/example.py --summary "Fixed locally." --why "Confirmed finding." --validation "python3 -m unittest=passed"
```


## Repository Layout Model

This git repository is the development and release wrapper around one shipped skill.

- Published skill payload: the entire `skill/` directory
- Repo-level verification harness: `tests/`
- Repo-level release and contributor files: `.github/`, `pyproject.toml`, `CHANGELOG.md`, root `AGENTS.md`, and other top-level metadata

Path convention:

- Repo-level docs and commands that execute runtime workflows use `gh-address-cr`
- Skill-owned docs inside `skill/` use paths relative to the skill root, such as `references/...` and `agents/openai.yaml`

If a rule or instruction must ship with the installed skill, it must live inside `skill/`, not only at repository root.


## Skill folder

- `skill/`
  - `SKILL.md`
  - `agents/openai.yaml`
  - `assets/reply-templates/*`
  - `references/cr-triage-checklist.md`
  - `runtime-requirements.json`


## What this skill provides

- PR-scoped session state for GitHub threads and local findings
- Strict per-item CR handling workflow
- Required evidence format (commit/files/test result)
- Mandatory final gate (`gh-address-cr final-gate`) before completion
- Session-scoped state tracking to avoid duplicate work
- Audit log + trace log + audit summary + summary hash output
- Audit summaries and `final-gate` output preserve machine-readable gate counts and summary hashes for evidence
- Python-first implementation with a single CLI entrypoint
- Module-split automated tests for session, wrappers, and helper scripts
