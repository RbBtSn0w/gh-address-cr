---
name: gh-address-cr
description: Use when a GitHub Pull Request needs review-thread reply and resolve handling, findings ingestion, and a mandatory final gate in one PR-scoped session.
argument-hint: "<review|threads|findings|adapter> ..."
---

# gh-address-cr

Use this skill as the thin adapter for the `gh-address-cr` runtime CLI.
The runtime owns session state, intake routing, GitHub side effects, leases, and the final gate.

## Usage

```text
/gh-address-cr review <owner/repo> <pr_number>
/gh-address-cr threads <owner/repo> <pr_number>
/gh-address-cr findings <owner/repo> <pr_number> --input <path>|-
/gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...>
```

## Packaging Scope

This file is part of the packaged `gh-address-cr` skill.
All paths in this document are relative to the installed skill root.

- `scripts/cli.py` is a compatibility shim that delegates to the external runtime CLI
- `references/...` means skill-owned reference docs
- `agents/openai.yaml` is an assistant-specific hint file inside the skill

A surrounding source repository may also contain repo-level tests, CI, and release metadata, but those are outside the packaged skill payload.

## Runtime Boundary

The packaged skill must not be treated as the implementation owner for workflow state.

- Runtime public entrypoint: `gh-address-cr`
- Module entrypoint: `python3 -m gh_address_cr`
- Compatibility shim: `python3 scripts/cli.py`
- Compatibility check: `python3 scripts/cli.py adapter check-runtime`

If the runtime is missing or incompatible, the shim must fail loudly before session mutation. Do not copy or reimplement runtime state-machine logic inside the skill payload.

## Agent Execution Ladder

Read this skill in this order when you are an AI agent:

1. Start from the public main entrypoint: `review <owner/repo> <pr_number>`.
2. Inspect the JSON machine summary output from the runtime.
3. Consult `references/status-action-map.md` to map the runtime `status`, `reason_code`, and `next_action` to your next safe step. You MUST branch your execution strictly based on these structured fields. Never parse or infer state from human prose or logs.
4. For multi-agent execution, use `agent orchestrate start`, `agent orchestrate step`, `agent orchestrate submit`, `agent orchestrate status`, and `agent orchestrate stop` through the runtime CLI.
5. Use `threads`, `findings`, `adapter`, and `review-to-findings` only as advanced/internal integration surfaces.

Fail-fast rules:

- `review` is the only public main entrypoint.
- `review-to-findings` does not accept arbitrary Markdown. It only accepts the fixed `finding` block format. This converter rejects plain narrative Markdown review output.
- AI agents must not post GitHub replies or resolve threads directly; the runtime records evidence and performs deterministic side effects.
- If a command outputs a `reason_code` or `next_action`, your next step MUST be determined solely by that code, ignoring all other prose in the `message` field.

## Machine Summary Contract

High-level commands emit structured JSON by default. Agents MUST consume these fields and MUST NOT parse human prose to determine system state:

- `status`
- `repo`
- `pr_number`
- `item_id`
- `item_kind`
- `counts`
- `artifact_path`
- `reason_code`
- `waiting_on`
- `next_action`
- `exit_code`

`reason_code` is the stable machine reason. `waiting_on` is the stable wait-state category.
`counts.*` may be `null` in preflight wait/fail states before GitHub or session scans run.
The `threads` command may also include a `threads` array with actionable GitHub thread context (`thread_id`, `path`, `line`, `body`, `url`, state/status, reply evidence, and accepted-response presence).

## Multi-Agent Protocol

Use the runtime as the coordinator:

- `gh-address-cr agent manifest`
  - discover supported roles, actions, formats, and protocol versions
- `gh-address-cr agent next <owner/repo> <pr_number> --role <role> --agent-id <id>`
  - claims one eligible item and writes an `ActionRequest`
- `gh-address-cr agent submit <owner/repo> <pr_number> --input <response.json>`
  - validates an `ActionResponse`, lease ownership, and required evidence
  - when it returns `ACTION_ACCEPTED`, run the returned `next_action`; accepted GitHub-thread fixes publish through `agent publish`
- `gh-address-cr agent leases <owner/repo> <pr_number>`
  - inspects active and terminal claims
- `gh-address-cr agent reclaim <owner/repo> <pr_number>`
  - expires stale leases without deleting accepted evidence

Role boundaries:

- coordinator: deterministic runtime CLI
- review_producer: emits normalized findings
- triage: classifies fix/clarify/defer/reject
- fixer: changes files and returns evidence
- verifier: checks submitted evidence
- publisher: deterministic runtime side-effect role
- gatekeeper: deterministic final-gate role

Allowed `ActionResponse.resolution` values are `fix`, `clarify`, `defer`, and `reject`.
Fix responses require changed files and validation evidence. Clarify/defer/reject responses require `reply_markdown` and validation evidence. GitHub side-effect claims from AI agents are invalid.

## Advanced References

- Dispatch details: `references/mode-producer-matrix.md`
- Review triage checklist: `references/cr-triage-checklist.md`
- Evidence ledger expectations: `references/evidence-ledger.md`
- Optional OTel -> Worker -> Better Stack logging: `references/otel-worker-better-stack.md`
- Low-level scripts are implementation details, not the public agent surface.

Examples that require advanced dispatch details live in the reference docs instead of the first-read contract.

## Entry Contract

Treat `SKILL.md` as the source of truth for using this skill.

- Start from the high-level dispatcher:
  - `python3 scripts/cli.py review <owner/repo> <pr_number>`
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

Advanced producer and dispatch details live in:

- `references/mode-producer-matrix.md`
- `references/cr-triage-checklist.md`

## Non-Negotiable Rule

`python3 scripts/cli.py final-gate` pass is mandatory before any completion statement.

- Never output "done", "all resolved", "completed", or equivalent unless:
  - `python3 scripts/cli.py final-gate <owner/repo> <pr_number>` has just passed, and
  - output includes `Verified: 0 Unresolved Threads found`, and
  - output includes `Verified: 0 Pending Reviews found`, and
  - session blocking item count is zero.
- Use `audit_summary.md` or the machine-readable count lines printed by `final-gate` when run-scoped diagnostics are needed.
- If gate fails, continue iteration; completion summary is forbidden.

## Core Rules

1. Use the high-level task entrypoints first:
  - `python3 scripts/cli.py review <owner/repo> <pr_number>`
  - `python3 scripts/cli.py threads <owner/repo> <pr_number>`
  - `python3 scripts/cli.py findings <owner/repo> <pr_number> --input <path>|-`
  - `python3 scripts/cli.py adapter <owner/repo> <pr_number> <adapter_cmd...>`
2. Use the internal low-level dispatch only when the high-level entrypoints do not fit.
3. Process only unresolved GitHub threads and open local findings.
4. For GitHub review threads, reply and resolve are both mandatory.
5. A GitHub thread is not terminally clean unless reply evidence exists with a concrete reply URL from the current authenticated GitHub login.
6. Outdated / `STALE` GitHub threads are still unresolved until explicitly handled.
7. For local findings, terminal handling must include a note.
8. `producer=code-review` must emit findings JSON before session handling starts.
9. Never declare completion before `python3 scripts/cli.py final-gate` passes.
10. Low-level resolve flows must refuse resolve-only handling when reply evidence is absent.


## Producer Contract

`gh-address-cr` is the orchestrator. Producers are replaceable.

- `code-review` is a producer, not the session owner.
- `code-review` here means "review-style findings producer", not one mandatory skill name.
- `code-review` now uses the built-in `code-review-adapter` backend for structured intake.
- If the upstream review output is fixed-format `finding` blocks, normalize it with `review-to-findings` before ingestion.
- `review-to-findings` does not accept arbitrary Markdown prose.
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




## Agent Feedback

- When the skill itself blocks progress, file a feedback issue against the skill repository before giving up.
- By default, feedback issues are filed to `RbBtSn0w/gh-address-cr`. Override `--target-repo` only when the skill owner explicitly directs you to use a different feedback repository.
- Use feedback issues for skill-level problems such as contradictory instructions, missing automation, documentation gaps, or repeatable tooling failures that are not caused by the repository under review.
- Do not file feedback issues for normal PR findings, code bugs in the target repository, or expected wait states such as `WAITING_FOR_EXTERNAL_REVIEW`.
- Do not include usernames, emails, tokens, machine names, or absolute local paths in feedback issues.
- Prefer safe technical diagnostics such as failing command, exit code, status, `reason_code`, `waiting_on`, `run_id`, and skill version.
- For PR-scoped feedback, always provide `--using-repo` and `--using-pr` so the issue body names the repository and pull request under review. If they are omitted, `submit_feedback.py` will try to infer them from `--source-command` or `--failing-command`, but explicit values are preferred.
- When `--using-repo` and `--using-pr` are present, `submit_feedback.py` auto-collects local PR-workspace evidence from `last-machine-summary.json`, `session.json`, `audit_summary.md`, and cached PR head SHA when those files exist.
- Repeated feedback is deduplicated by fingerprint; if the same feedback issue is already open, or was closed recently inside the cooldown window, the helper returns the existing issue instead of creating a new one.
- Use `python3 scripts/submit_feedback.py` with explicit fields so the body matches the repository issue format:
  - `--category`
  - `--title`
  - `--summary`
  - `--expected`
  - `--actual`
  - optional `--source-command`, `--failing-command`, `--exit-code`, `--status`, `--reason-code`, `--waiting-on`, `--run-id`, `--skill-version`, `--using-repo`, `--using-pr`, `--artifact`, and `--notes`
- Example:
  - `python3 scripts/submit_feedback.py --category workflow-gap --title "blocked without a recovery step" --summary "review stopped in a blocked state without enough operator guidance." --expected "the skill should identify the next command or artifact to inspect." --actual "the workflow stopped and the next action was ambiguous." --source-command "python3 scripts/cli.py review owner/repo 123" --failing-command "python3 scripts/cli.py final-gate owner/repo 123" --exit-code 5 --status BLOCKED --reason-code WAITING_FOR_FIX --waiting-on human_fix --run-id cr-loop-20260417T120000Z --skill-version 1.2.0 --using-repo owner/repo --using-pr 123 --artifact /tmp/loop-request.json`
  - `python3 scripts/cli.py submit-feedback --category workflow-gap --title "blocked without a recovery step" --summary "review stopped in a blocked state without enough operator guidance." --expected "the skill should identify the next command or artifact to inspect." --actual "the workflow stopped and the next action was ambiguous."`


## Completion Contract

Final output must include:

1. `final_gate` command used
2. `Verified: 0 Unresolved Threads found`
3. `Verified: 0 Pending Reviews found`
4. unresolved GitHub threads = 0
5. session blocking items = 0
6. audit summary path + sha256

For run-scoped diagnostics, use:

- `python3 scripts/audit_report.py --run-id <run_id> <owner/repo> <pr_number>`
- successful `python3 scripts/cli.py final-gate --auto-clean ...` runs archive the PR workspace before deletion under `archive/<owner>__<repo>/pr-<pr>/<run_id>/`


## Why CR Appears Later (Use This Exact Logic)

- GitHub review bots run asynchronously.
- New commits trigger re-analysis and can generate new comments.
- Old threads can become outdated; new ones may appear on different lines.

## References

- dispatch matrix: `references/mode-producer-matrix.md`
- checklist: `references/cr-triage-checklist.md`
- stable operator surface: `python3 scripts/cli.py`
- preferred automation surface: `python3 scripts/cli.py ...`
- AI agent feedback helper: `python3 scripts/submit_feedback.py`
- code-review bridge prompt: `python3 scripts/cli.py prepare-code-review <local|mixed> <owner/repo> <pr_number>`
- Markdown-to-findings converter: `python3 scripts/cli.py review-to-findings <owner/repo> <pr_number> --input -`
- code-review adapter backend: `python3 scripts/cli.py code-review-adapter --input -`

Examples:

```text
$gh-address-cr review <PR_URL>
$gh-address-cr threads <PR_URL>
$gh-address-cr findings <PR_URL> --input findings.json
$gh-address-cr findings <PR_URL> --input - --sync
$gh-address-cr adapter <PR_URL> <adapter_cmd...>
$gh-address-cr review-to-findings <owner/repo> <pr_number> --input -
```

If `review` returns `BLOCKED`, inspect the loop request artifact, apply `fix`, `clarify`, or `defer`, then rerun the same `review` command.

Outdated / `STALE` GitHub threads are still unresolved until explicitly handled.
