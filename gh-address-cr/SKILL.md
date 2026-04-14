---
name: gh-address-cr
description: Use when a GitHub Pull Request needs review-thread reply/resolve handling, local findings ingestion, and a mandatory final gate in one PR-scoped session.
argument-hint: "<mode> [producer] <owner/repo> <pr_number>"
---

# gh-address-cr

Use this skill as the PR review control plane. It owns session state, intake routing, and the final gate.

## Usage

```text
/gh-address-cr remote <owner/repo> <pr_number>
/gh-address-cr local <producer> <owner/repo> <pr_number>
/gh-address-cr mixed <producer> <owner/repo> <pr_number>
/gh-address-cr ingest [producer=json] <owner/repo> <pr_number>
/gh-address-cr loop <mode> [producer] <owner/repo> <pr_number>
```

`mode`
- `remote`: GitHub review threads only
- `local`: local findings only
- `mixed`: GitHub review threads plus local findings
- `ingest`: import existing findings JSON

`producer`
- `code-review`: findings must be produced as structured JSON first
- `json`: findings already exist as JSON
- `adapter`: an adapter command prints findings JSON

## Entry Contract

Treat `SKILL.md` as the source of truth for using this skill.

- Start from the high-level dispatcher:
  - `python3 scripts/cli.py control-plane <mode> [producer] <owner/repo> <pr_number> ...`
  - `python3 scripts/cli.py cr-loop <mode> [producer] <owner/repo> <pr_number> ...`
- Use `references/mode-producer-matrix.md` only for mode-specific dispatch details.
- Do not rely on `agents/openai.yaml` for unique behavior; it is only a thin assistant-specific hint layer.

## Capability Status

These paths are fully operational now:

- `remote`
- `local code-review`
- `local json`
- `local adapter`
- `mixed code-review`
- `mixed json`
- `mixed adapter`
- `ingest json`
- `loop remote`
- `loop local json`
- `loop local code-review`
- `loop mixed adapter`

For `producer=code-review`, the execution model is:

- generate the bridge prompt with `prepare-code-review`
- run the external review step and produce findings JSON first
- if findings already exist as a real file, pass that file with `--input <path>`
- if findings are being produced in the current step, prefer piping them through `stdin` with `--input -`
- let `control-plane` pass that JSON through the built-in `code-review-adapter`

Do not assume `gh-address-cr` directly runs another review skill by itself. The review step is still external; the intake path is now adapter-backed and stable.

## Non-Negotiable Rule

`final_gate.sh` pass is mandatory before any completion statement.

- Never output "done", "all resolved", "completed", or equivalent unless:
  - `scripts/final_gate.sh <owner/repo> <pr_number>` has just passed, and
  - output includes `Verified: 0 Unresolved Threads found`, and
  - session blocking item count is zero.
- If gate fails, continue iteration; completion summary is forbidden.

## Core Rules

1. Pick exactly one `mode` and, when required, exactly one `producer`.
2. Use the high-level dispatcher first:
  - `python3 scripts/cli.py control-plane <mode> [producer] <owner/repo> <pr_number> ...`
   - or `python3 scripts/cli.py cr-loop <mode> [producer] <owner/repo> <pr_number> ...` for multi-iteration execution
3. Process only unresolved GitHub threads and open local findings.
4. For GitHub review threads, reply and resolve are both mandatory.
5. For local findings, terminal handling must include a note.
6. `producer=code-review` must emit findings JSON before session handling starts.
7. Never declare completion before `final_gate.sh` passes.

## Loop Contract

Use `cr-loop` when you want `gh-address-cr` to run multiple iterations automatically.

- `cr-loop` still treats `gh-address-cr` as the control plane.
- By default, the loop uses the current AI agent as the internal fixer handoff path.
- If no `--fixer-cmd` is provided, `cr-loop` writes an internal fixer request JSON into the PR artifacts directory and exits `BLOCKED` until the agent handles that item.
- `--fixer-cmd "<command>"` remains available as an advanced external fixer override.
- External fixer commands must read a JSON payload from stdin and return a JSON object containing:
  - `resolution`: `fix`, `clarify`, or `defer`
  - `note`
  - `reply_markdown` for GitHub thread items
  - optional `validation_commands`
- `code-review` and `json` producers are consumed once per loop run.
- `adapter` producer is re-run on each iteration.
- The loop exits as:
  - `PASSED` when gate succeeds
  - `NEEDS_HUMAN` when retry thresholds are exceeded
  - `BLOCKED` when a non-recoverable orchestration step fails

## Producer Contract

`gh-address-cr` is the control plane. Producers are replaceable.

- `code-review` is a producer, not the session owner.
- `code-review` now uses the built-in `code-review-adapter` backend for structured intake.
- `gh-address-cr` only assumes the normalized finding contract:
  - `title`
  - `body`
  - `path`
  - `line`
- Accepted findings input shapes:
  - JSON array of finding objects
  - JSON object with `findings`, `issues`, or `results`
  - NDJSON, one finding object per line
- Accepted field aliases:
  - `path` or `file` or `filename`
  - `line` or `start_line` or `position`
  - `title` or `rule` or `check`
  - `body` or `message` or `description`
- Input path rule:
  - use `--input <path>` only when a producer already emitted a real JSON file
  - otherwise prefer `--input -` and pipe findings through `stdin`
  - do not create ad-hoc temporary findings files in the project workspace just to drive the workflow
- Supported dispatch paths live in:
  - `references/mode-producer-matrix.md`

## Discovery Rules

Use this skill when the task involves one or more of these needs:

- handle GitHub PR review threads with explicit reply and resolve steps
- ingest local review findings into a PR-scoped session
- run a final gate before declaring review completion
- keep remote threads and local findings under one auditable PR session

Do not use this skill as the review engine itself.

- It manages intake, state, processing discipline, and gating.
- It does not own the reasoning logic of external review producers.

## Decision Matrix

- **Accept**: real bug or low-cost valid improvement; fix and provide evidence.
- **Clarify**: reviewer misunderstood the code; explain without changing code.
- **Defer**: non-blocking or high-cost preference; explain the tradeoff.
- **Reject**: suggestion is technically incorrect, conflicts with the current contract, or would break an intentional compatibility guarantee.

## Fix Selection Rules

Before changing code, classify each item in this order:

1. **Validity**
   - `confirmed`: reproducible in current HEAD or directly supported by code/tests
   - `unclear`: not yet verified; do not implement blindly
   - `rejected`: technically incorrect or based on missing context
2. **Impact**
   - Does it affect correctness, session/gate consistency, runtime safety, compatibility, packaging, or CI?
3. **Scope Fit**
   - Is the fix local to the current PR, or does it expand into a new design decision or larger refactor?
4. **Decision**
   - `fix`, `clarify`, `defer`, or `reject`

Use these defaults:

- Default to `fix` for correctness bugs, state mismatches, concurrency hazards, compatibility regressions, install/runtime breakage, and P1/P2 issues that can be verified.
- Default to `clarify` when behavior is intentional and the reviewer lacks context.
- Default to `defer` when the issue is real but out of scope for the current PR or would force broader redesign.
- Default to `reject` when the suggestion is technically unsound or would violate an explicit workflow contract.

Do not change code until the item has been validated and classified.

## Scope Guardrails

Do not "fix" items just to make the thread disappear.

- Do not expand the PR with unrelated refactors.
- Do not change public behavior for style-only comments.
- Do not weaken compatibility defaults unless the review identifies a real regression.
- Do not let a reviewer preference override an existing, tested contract without explicit product intent.

If a review item is real but not appropriate for the current PR, reply with `defer` and a concrete rationale instead of stretching scope.

## Needs-Human Escalation

Prefer `NEEDS_HUMAN` over speculative fixes when:

- the claim cannot be verified from the codebase or tests
- two valid concerns conflict and require a product decision
- the fix would create a new interface or contract
- the same item keeps reopening after multiple technically sound attempts
- the suggestion conflicts with an intentional compatibility or workflow rule and the tradeoff is not obvious

`gh-address-cr` should stop loop iteration and escalate rather than forcing an implementation under uncertainty.

## Required Evidence

- Accepted GitHub thread:
  - commit
  - touched files
  - validation command and result
- Clarified or deferred item:
  - rationale
- Local finding terminal state:
  - note

## Completion Contract

Final output must include:

1. `final_gate` command used
2. `Verified: 0 Unresolved Threads found`
3. unresolved GitHub threads = 0
4. session blocking items = 0
5. audit summary path + sha256

## Must-Fix Rule

- Default must-fix: correctness bugs, data loss risks, platform/runtime breakage, packaging/install breakage, P1/P2 regressions.
- Can defer with rationale: style-only, naming preference, non-blocking wording improvements.
- For this repo, fix priority is:
  - session / gate / loop semantic mismatches
  - GitHub reply / resolve / pending-review visibility issues
  - CLI and shell-wrapper compatibility regressions
  - workspace/cache side effects
  - test and CI breakage caused by real implementation changes
  - documentation/runtime mismatches that mislead actual usage

## Why CR Appears Later (Use This Exact Logic)

- GitHub review bots run asynchronously.
- New commits trigger re-analysis and can generate new comments.
- Old threads can become outdated; new ones may appear on different lines.

## References

- dispatch matrix: `references/mode-producer-matrix.md`
- checklist: `references/cr-triage-checklist.md`
- stable operator surface: `scripts/*.sh`
- preferred automation surface: `python3 scripts/cli.py ...`
- loop runner: `python3 scripts/cli.py cr-loop <mode> [producer] <owner/repo> <pr_number> [--fixer-cmd "<command>"]`
- code-review bridge prompt: `python3 scripts/cli.py prepare-code-review <local|mixed> <owner/repo> <pr_number>`
- code-review adapter backend: `python3 scripts/cli.py code-review-adapter --input -`
