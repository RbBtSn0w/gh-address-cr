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
/gh-address-cr ingest <producer> <owner/repo> <pr_number>
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
- Use `references/mode-producer-matrix.md` only for mode-specific dispatch details.
- Do not rely on `agents/openai.yaml` for unique behavior; it is only a thin assistant-specific hint layer.

## Capability Status

These paths are fully operational now:

- `remote`
- `local json`
- `local adapter`
- `mixed json`
- `mixed adapter`
- `ingest json`

These paths are contract-supported but not yet auto-bridged:

- `local code-review`
- `mixed code-review`

For `producer=code-review`, the current requirement is:

- generate the bridge prompt with `prepare-code-review`
- produce findings JSON first
- then feed it through `control-plane` or `ingest-findings`

Do not assume `gh-address-cr` directly runs another review skill by itself yet.

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
3. Process only unresolved GitHub threads and open local findings.
4. For GitHub review threads, reply and resolve are both mandatory.
5. For local findings, terminal handling must include a note.
6. `producer=code-review` must emit findings JSON before session handling starts.
7. Never declare completion before `final_gate.sh` passes.

## Producer Contract

`gh-address-cr` is the control plane. Producers are replaceable.

- `code-review` is a producer, not the session owner.
- `gh-address-cr` only assumes the normalized finding contract:
  - `title`
  - `body`
  - `path`
  - `line`
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

## Why CR Appears Later (Use This Exact Logic)

- GitHub review bots run asynchronously.
- New commits trigger re-analysis and can generate new comments.
- Old threads can become outdated; new ones may appear on different lines.

## References

- dispatch matrix: `references/mode-producer-matrix.md`
- checklist: `references/cr-triage-checklist.md`
- stable operator surface: `scripts/*.sh`
- preferred automation surface: `python3 scripts/cli.py ...`
- code-review bridge prompt: `python3 scripts/cli.py prepare-code-review <local|mixed> <owner/repo> <pr_number>`
