---
name: gh-address-cr
description: This skill is used when a GitHub Pull Request needs review-thread reply/resolve handling, local findings ingestion, and a mandatory final gate in one PR-scoped session.
argument-hint: "<review|threads|findings|adapter> ..."
---

# gh-address-cr

Use this skill as the PR review orchestrator. It owns session state, intake routing, and the final gate.

## Usage

```text
/gh-address-cr review <owner/repo> <pr_number>
/gh-address-cr threads <owner/repo> <pr_number>
/gh-address-cr findings <owner/repo> <pr_number>
/gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...>
```

## Agent Execution Ladder

Read this skill in this order when you are an AI agent:

1. Decide whether you already have findings JSON.
2. If you already have a real JSON file, pass it with `--input <path>`.
3. If findings are produced in the current step, pipe them through `stdin` with `--input -`.
4. If the upstream tool only prints Markdown review blocks, convert them first with `review-to-findings`.
5. Then invoke the `gh-address-cr` entrypoint that consumes those findings.

Fail-fast rules:

- `review` and `findings` require explicit findings input.
- `review` does not generate findings; it only consumes findings JSON and orchestrates session/gate handling.
- If `--input` is missing, the CLI fails immediately instead of waiting on `stdin`.
- `review`, `threads`, and `adapter` require `gh` on `PATH` and fail immediately when it is missing.
- The high-level CLI commands are the only agent-safe public surface. Treat low-level scripts as internal implementation details.

Important:

- `review` is the default end-to-end orchestrator, not a hidden review producer.
- `threads` handles GitHub threads only.
- `findings` handles existing findings JSON only.
- `adapter` handles a command that prints findings JSON.

Recommended high-level entrypoints:

- `review`
  - default entrypoint
  - runs the full PR review workflow automatically once findings are supplied
- `threads`
  - GitHub review threads only
- `findings`
  - existing findings JSON only
- `adapter`
  - adapter command prints findings JSON

Examples:

```text
$gh-address-cr review <PR_URL>
$gh-address-cr threads <PR_URL>
$gh-address-cr findings <PR_URL> --input findings.json
$gh-address-cr findings <PR_URL> --input - --sync
$gh-address-cr adapter <PR_URL> <adapter_cmd...>
```

Advanced dispatch model:

- `mode`
  - `remote`: GitHub review threads only
  - `local`: local findings only
  - `mixed`: GitHub review threads plus local findings
  - `ingest`: import existing findings JSON
- `producer`
  - `code-review`: any review-style producer that emits structured findings JSON first
  - `json`: findings already exist as JSON
  - `adapter`: an adapter command prints findings JSON

Examples:

```text
// A review skill runs first, then gh-address-cr ingests the JSON
<review-command> <PR_URL> --output findings.json
$gh-address-cr findings <PR_URL> --input findings.json --sync

// The same pattern with stdin instead of a file
<review-command> <PR_URL> | $gh-address-cr findings <PR_URL> --input - --sync

// Markdown-only review output becomes findings JSON first
<review-command> <PR_URL> | $gh-address-cr review-to-findings <owner/repo> <pr_number> > findings.json
$gh-address-cr findings <PR_URL> --input findings.json --sync

// The upstream producer is still category=code-review even if the tool name differs
$gh-address-cr review <PR_URL>
```

## Entry Contract

Treat `SKILL.md` as the source of truth for using this skill.

- Start from the high-level dispatcher:
  - `python3 scripts/cli.py review <owner/repo> <pr_number> [--input <path>|-]`
  - `python3 scripts/cli.py threads <owner/repo> <pr_number>`
  - `python3 scripts/cli.py findings <owner/repo> <pr_number> --input <path>|- [--sync]`
  - `python3 scripts/cli.py adapter <owner/repo> <pr_number> <adapter_cmd...>`
- Use `references/mode-producer-matrix.md` only for mode-specific dispatch details.
- Do not rely on `agents/openai.yaml` for unique behavior; it is only a thin assistant-specific hint layer.

## Capability Status

These high-level paths are fully operational now:

- `review`
- `threads`
- `findings`
- `adapter`

The internal iteration and dispatch layers are implementation details and are not part of the public entrypoint surface.

For `producer=code-review`, the execution model is:

- generate the bridge prompt with `prepare-code-review`
- run the external review step and produce findings JSON first
- if findings already exist as a real file, pass that file with `--input <path>`
- if findings are being produced in the current step, prefer piping them through `stdin` with `--input -`
- let the intake layer pass that JSON through the built-in `code-review-adapter`

`producer=code-review` is a contract label, not a hardcoded dependency on one specific skill name.

- It can be `/code-review`
- It can be `/code-review-aa`
- It can be `/code-review-bb`
- It can be an agent-native review command that only runs before `gh-address-cr`

The only requirement is that the upstream review step emits findings in the accepted JSON shapes. Do not assume `gh-address-cr` directly runs another review skill by itself. The review step is still external; the intake path is now adapter-backed and stable.

## Non-Negotiable Rule

`python3 gh-address-cr/scripts/cli.py final-gate` pass is mandatory before any completion statement.

- Never output "done", "all resolved", "completed", or equivalent unless:
  - `python3 gh-address-cr/scripts/cli.py final-gate <owner/repo> <pr_number>` has just passed, and
  - output includes `Verified: 0 Unresolved Threads found`, and
  - session blocking item count is zero.
- If gate fails, continue iteration; completion summary is forbidden.

## Core Rules

1. Use the high-level task entrypoints first:
  - `python3 scripts/cli.py review <owner/repo> <pr_number> [--input <path>|-]`
  - `python3 scripts/cli.py threads <owner/repo> <pr_number>`
  - `python3 scripts/cli.py findings <owner/repo> <pr_number> --input <path>|-`
  - `python3 scripts/cli.py adapter <owner/repo> <pr_number> <adapter_cmd...>`
2. Use the internal low-level dispatch only when the high-level entrypoints do not fit.
3. Process only unresolved GitHub threads and open local findings.
4. For GitHub review threads, reply and resolve are both mandatory.
5. For local findings, terminal handling must include a note.
6. `producer=code-review` must emit findings JSON before session handling starts.
7. Never declare completion before `python3 gh-address-cr/scripts/cli.py final-gate` passes.

## Automatic Iteration

The default review entrypoint runs repeated intake, item selection, action execution, and gate evaluation internally until the PR session converges.

- The internal fixer handoff path uses the current AI agent by default.
- If a finding cannot be resolved automatically, the workflow records an internal fixer request artifact for the agent to handle.
- Advanced external fixer commands remain available for integrations that need an explicit command boundary.
- External fixer commands must read a JSON payload from stdin and return a JSON object containing:
  - `resolution`: `fix`, `clarify`, or `defer`
  - `note`
  - `reply_markdown` for GitHub thread items
  - optional `validation_commands`
- `code-review` and `json` producers are consumed once per review run.
- `adapter` producer is re-run on each iteration.
- The workflow exits as:
  - `PASSED` when gate succeeds
  - `NEEDS_HUMAN` when retry thresholds are exceeded
  - `BLOCKED` when a non-recoverable orchestration step fails

## Producer Contract

`gh-address-cr` is the orchestrator. Producers are replaceable.

- `code-review` is a producer, not the session owner.
- `code-review` here means "review-style findings producer", not one mandatory skill name.
- `code-review` now uses the built-in `code-review-adapter` backend for structured intake.
- If the upstream review output is Markdown review blocks, normalize it with `review-to-findings` before ingestion.
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
- Refresh rule:
  - use `--sync` when re-ingesting the same source and you want missing local findings to auto-close
- Supported dispatch paths live in:
  - `references/mode-producer-matrix.md`

## Prompt Patterns

When `gh-address-cr` is the main entrypoint, prefer:

```text
$gh-address-cr review <PR_URL>

Use the upstream review producer to emit findings JSON first, then let $gh-address-cr ingest, process, and gate the PR session.
If the upstream tool emits Markdown review blocks, convert them first with `review-to-findings`, then feed the resulting JSON to `gh-address-cr`.
If the findings are produced in the current step, prefer `--input -` and stdin.
```

When an external review command must run first and `gh-address-cr` can only come second, prefer:

```text
First run <review-command> on <PR_URL> and emit findings JSON, not Markdown only.
If the command only emits Markdown review blocks, convert them first with `review-to-findings`.
Then hand the findings to $gh-address-cr using `findings` or `review`, depending on whether the input is already a JSON file.
Use --input <path> only for an already-existing JSON file; otherwise prefer --input - with stdin.
Add `--sync` when you want missing findings from the same source to auto-close on refresh.
```

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

`gh-address-cr` should stop iteration and escalate rather than forcing an implementation under uncertainty.

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
  - session / gate / iteration semantic mismatches
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
- stable operator surface: `python3 gh-address-cr/scripts/cli.py`
- preferred automation surface: `python3 scripts/cli.py ...`
- code-review bridge prompt: `python3 scripts/cli.py prepare-code-review <local|mixed> <owner/repo> <pr_number>`
- Markdown-to-findings converter: `python3 scripts/cli.py review-to-findings <owner/repo> <pr_number> --input -`
- code-review adapter backend: `python3 scripts/cli.py code-review-adapter --input -`
