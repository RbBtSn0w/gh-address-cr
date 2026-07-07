---
name: gh-address-cr
description: Use when a GitHub Pull Request has unresolved review threads, pending reviews, stale/outdated threads, local findings ingestion, or needs mandatory final-gate proof in one PR-scoped session.
argument-hint: "<active-pr|review|address|threads|findings|adapter|doctor|agent|final-gate|command-session|submit-feedback> ..."
---

# gh-address-cr

Use this skill as the thin adapter for the `gh-address-cr` runtime CLI. The runtime owns session state, intake routing, GitHub side effects, leases, reply/resolve publication, and the final gate.

## Primary Commands

```text
/gh-address-cr active-pr [--repo <owner/repo>] [--head <branch>]
/gh-address-cr review <owner/repo> <pr_number> [--auto-simple]
/gh-address-cr address <owner/repo> <pr_number> [--lean|--summary]
/gh-address-cr threads <owner/repo> <pr_number> [--lean|--summary]
/gh-address-cr findings <owner/repo> <pr_number> --input <path>|-
/gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...>
/gh-address-cr review-to-findings <owner/repo> <pr_number> --input <finding-blocks.md>|-
/gh-address-cr doctor [<owner/repo> [<pr_number>]]
/gh-address-cr final-gate <owner/repo> <pr_number>
/gh-address-cr command-session --input <commands.json>|-
/gh-address-cr submit-action <action-request.json> --resolution <fix|clarify|defer|reject> ...
/gh-address-cr submit-feedback --category <category> --title <title> --summary <summary> ...
/gh-address-cr version
```

Agent protocol commands:

```text
/gh-address-cr agent manifest
/gh-address-cr agent classify <owner/repo> <pr_number> <item_id> --classification <fix|clarify|defer|reject> --note <why>
/gh-address-cr agent next <owner/repo> <pr_number> --role <role> --agent-id <id>
/gh-address-cr agent next <owner/repo> <pr_number> --batch --agent-id <id>
/gh-address-cr agent submit <owner/repo> <pr_number> --input <response.json>
/gh-address-cr agent resolve <owner/repo> <pr_number> <item_id> --commit <sha> --files <paths> --summary <text> --why <text> --validation <cmd=passed@<ms>ms>
/gh-address-cr agent resolve <owner/repo> <pr_number> <item_id> --trivial --commit <sha> --files <paths> --summary <text> --why <text> --validation <cmd=passed@<ms>ms>
/gh-address-cr agent resolve <owner/repo> <pr_number> --batch --input <batch-response.json>
/gh-address-cr agent resolve <owner/repo> <pr_number> --commit <sha> --files <paths> --validation <cmd=passed@<ms>ms> --homogeneous-reason <why>
/gh-address-cr agent resolve <owner/repo> <pr_number> --reject|--clarify --match-files --files <paths> --homogeneous-reason <why>
/gh-address-cr agent resolve <owner/repo> <pr_number> --commit <sha> --files <paths> --validation <cmd=passed@<ms>ms> --stale --match-files
/gh-address-cr agent evidence add <owner/repo> <pr_number> --name <profile> --commit <sha> --files <paths> --validation <cmd=passed@<ms>ms>
/gh-address-cr agent evidence add <owner/repo> <pr_number> --item-id <item_id> --reply-url <reply_url> --author-login <login>
/gh-address-cr agent publish <owner/repo> <pr_number>
/gh-address-cr agent leases <owner/repo> <pr_number>
/gh-address-cr agent reclaim <owner/repo> <pr_number>
/gh-address-cr agent orchestrate <start|step|status|stop|resume|submit|autopilot> ...
```

Examples:

```text
$gh-address-cr review <PR_URL>
$gh-address-cr address <PR_URL> --lean
$gh-address-cr review --auto-simple <PR_URL>
$gh-address-cr threads <PR_URL> --lean
$gh-address-cr findings <PR_URL> --input findings.json
$gh-address-cr findings <PR_URL> --input - --sync --source <producer>
$gh-address-cr adapter <PR_URL> <adapter_cmd...>
$gh-address-cr review-to-findings <owner/repo> <pr_number> --input -
```

## Packaging Scope

This file is part of the packaged `gh-address-cr` skill. All paths in this document are relative to the installed skill root.

- `references/...` means skill-owned reference docs.
- `agents/openai.yaml` is an assistant-specific hint file inside the skill.

A surrounding source repository may also contain repo-level tests, CI, and release metadata, but those are outside the packaged skill payload.

## Runtime Boundary

The packaged skill must not be treated as the implementation owner for workflow state.

- Runtime public entrypoint: `gh-address-cr`
- Module entrypoint: `python3 -m gh_address_cr`
- Compatibility check: `gh-address-cr adapter check-runtime`

If the runtime is missing, execution must fail loudly before session mutation. Do not copy or reimplement runtime state-machine logic inside the skill payload.

## Telemetry Coverage

To make `final-gate` produce a meaningful telemetry summary line during a normal
run, carry measured timing on every `--validation`. Add a `@<n>ms` (or
`@<n>s`) suffix to each command result so the runtime records real duration.
Bare `cmd=passed` records zero duration and emits a
`TELEMETRY_TIMING_UNAVAILABLE` diagnostic with an empty `duration`/`slowest`
line.

```text
gh-address-cr agent resolve <owner/repo> <pr_number> <item_id> --commit <sha> \
  --files <paths> --summary "..." --why "..." \
  --validation "typecheck=passed@1800ms" --validation "unit-tests=passed@4200ms"

gh-address-cr final-gate <owner/repo> <pr_number>
```

Completion evidence from `final-gate` must report the telemetry coverage label:
`complete`, `partial`, `runtime-only`, or `unavailable`. Final user-facing
completion responses must include the exact `completion_summary_line` from
`final-gate --machine` or the first bracketed line from
`PR Completion Summary Guidance`; that line contains telemetry coverage,
confidence, source scope, observed duration, slowest operation, and issue
summary. This is runtime telemetry for the surviving core path. Telemetry degradation is a coverage/reporting fact, not
review-resolution evidence.

When recording validation evidence via `agent resolve ... --validation <cmd=result>`, include the measured runtime as a suffix so efficiency reports can analyze duration: `--validation "ruff check=passed@1500ms"` (also accepts `@<n>s`). Omitting the suffix is allowed but records the command with zero duration, and the efficiency report will label timing as unavailable via a `TELEMETRY_TIMING_UNAVAILABLE` diagnostic instead of presenting misleading `0ms` slowest-operation rows.

Telemetry degradation is visible but does not block core PR completion by
itself: `final-gate` reports coverage, diagnostics, and overhead budget
findings while preserving review-state pass/fail authority. If diagnostics
include `TELEMETRY_OVERHEAD_EXCEEDED`, report the impact in the completion
summary instead of retrying the review workflow. `runtime-only` coverage is an
advisory local-loop condition when host telemetry was not imported; mention it
briefly instead of escalating it as a gate blocker. Briefly explain abnormal
coverage, diagnostics, success-rate drops, or inefficiency flags in the final
response instead of hiding them behind artifact paths.

When exactly one cached PR session exists, PR-scoped commands may omit `<owner/repo> <pr_number>`. If the runtime reports `NO_ACTIVE_PR_SCOPE` or `AMBIGUOUS_PR_SCOPE`, pass the target explicitly instead of guessing.

### Session Correlation

Each `gh-address-cr` invocation emits one OpenTelemetry span carrying the
sanitized command, exit outcome, and (when identifiable) the GitHub PR being
worked on. To let an observability backend group every invocation from the
current agent session together, export a stable, per-session identifier as
`GH_ADDRESS_CR_CONVERSATION_ID` before invoking any `gh-address-cr` command,
and keep the same value for every invocation within that session:

```text
export GH_ADDRESS_CR_CONVERSATION_ID="<a stable id unique to this session>"
```

This is optional and additive: omitting it does not change command behavior,
output, or exit codes. Some hosts (Claude Code) are already detected
automatically with no action needed; setting `GH_ADDRESS_CR_CONVERSATION_ID`
is the vendor-neutral way to get the same correlation on any host.

## Execution Ladder

1. If the PR number is unknown, run `active-pr`; it only returns OPEN PRs and fails loud for none or many.
2. Start from the public main entrypoint: `review <owner/repo> <pr_number>`, or `address <owner/repo> <pr_number> --lean` for simple GitHub-thread-only PRs.
3. Inspect the JSON machine summary. Prefer `--lean` or `--summary` on `address`, `threads`, and `review --auto-simple` when thread lists are large.
4. Consult `references/status-action-map.md` and branch strictly on `status`, `reason_code`, `waiting_on`, `next_action`, and `commands`.
5. Start from the runtime dispatcher:
  - `gh-address-cr review <owner/repo> <pr_number>`
  - `gh-address-cr address <owner/repo> <pr_number> --lean`
  - `gh-address-cr threads <owner/repo> <pr_number> --lean`
  - `gh-address-cr findings <owner/repo> <pr_number> --input <path>|- [--sync --source <producer>]`
  - `gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...>`
  - `gh-address-cr agent manifest`

If `review` returns `BLOCKED`, inspect the loop request artifact, apply `fix`, `clarify`, `defer`, or `reject` through runtime evidence, then rerun the same `review` command.

GitHub review comment reply tasks must be submitted to the runtime before they can be published. The single mutating entrypoint is `gh-address-cr agent resolve`; it records classification internally, so no separate `agent classify` step is needed on this path. For one thread, run `agent resolve <item_id> --commit <sha> --files <paths> --summary <text> --why <text> --validation <cmd=passed@<ms>ms>`. When one set of files/validation evidence addresses multiple threads, run `gh-address-cr agent next <owner/repo> <pr_number> --batch --agent-id <id>` to claim eligible GitHub review threads and write a fillable batch skeleton, then `agent resolve --batch --input <batch-response.json>` keeping per-thread summary/why entries. Use `agent resolve --homogeneous-reason <why>` only for a homogeneous repeated concern, `agent resolve --trivial` only for documentation or typo-only threads (else `TRIVIAL_THREAD_NOT_ELIGIBLE`), and `agent resolve --stale --match-files` for STALE/outdated threads. To **decline** (not fix) the same repeated concern across many threads with one shared reply, use `agent resolve --reject|--clarify --homogeneous-reason <why> --match-files` (no commit/validation); the same body-identity gate blocks declining threads that raise distinct concerns. Then run `gh-address-cr agent publish <owner/repo> <pr_number>` so the runtime hydrates commit evidence, records reply evidence, and resolves the thread safely. `agent publish` is the single canonical publish path; each `agent resolve` form also accepts `--publish` to publish accepted evidence immediately and reports `published` in its result. The granular `agent classify` / `agent next` / `agent submit` commands remain available as the low-level protocol that `resolve` is built on.

If `final-gate` reports `FINAL_GATE_MISSING_REPLY_EVIDENCE` for a thread that is already terminal and no longer claimable, do not loop on `agent publish`. Use `gh-address-cr agent evidence add <owner/repo> <pr_number> --item-id <item_id> --reply-url <reply_url> --author-login <login>` to reconcile durable reply evidence, then rerun `final-gate`.

If item-mode `agent resolve <item_id> ...` reports `LEASE_LOCKED_ITEM`, inspect `lease_recovery` and run `gh-address-cr agent leases <owner/repo> <pr_number>` before retrying. The blocking condition is active lease ownership, not “no work”.

If a blocked command reports `GH_PERMISSION_MISMATCH`, treat it as wrapper/runtime grant drift. Inspect `diagnostics.source_scope`, sync the wrapper-visible GitHub permissions with the active runner grants, then rerun the same command.

When resolving, record each `--validation` with its measured timing suffix
(`@<n>ms`/`@<n>s`) so efficiency reporting has real duration. Run
`final-gate` last and surface its exact `completion_summary_line`; see the
telemetry guidance above.

Prefer `workflow_decision.v1` JSON for structured triage handoff when available. Required fields are `schema_version`, `request_id`, `item_id`, `decision`, and `reason`; Markdown decision blocks remain compatibility prose, not the preferred machine contract.

Use `command-session --input -` to reduce repeated process startup for multiple runtime operations. Treat each returned operation result independently; a failed step does not prove later steps were skipped.

`agent orchestrate` is an optional advanced surface. Use it only when a
workflow truly needs orchestration state; the default supported path remains
single-agent `review` / `address` / `agent resolve` / `agent publish` /
`final-gate`.

If an external producer result is already available, `findings --input <path>|- --source <producer> [--sync]` may satisfy the same PR session handoff as `incoming-findings.json`. A successful ingest records the producer result in session state; `[]` is an explicit empty result, while empty stdin is not.

## Common Mistakes

- Do not infer state from human prose or logs. Use only structured machine fields and the status-action map.
- Do not post GitHub replies or resolve review threads directly. The runtime records evidence and performs deterministic side effects.
- Do not treat `STALE` or outdated GitHub threads as clean. Outdated / `STALE` GitHub threads are still unresolved until explicitly handled.
- Do not invent severity. Only explicit `P0`, `P1`, `P2`, `P3`, or `P4` evidence from the producer payload or the original GitHub review-thread comment should become session severity. Leave unknown severity unknown; reviewer `high/medium/low priority` text is raw priority evidence, not a P-scale mapping. Published fix replies should surface exactly one canonical `Review signal:` line for either trusted P-scale severity or raw reviewer priority, and omit the line when neither signal is present.
- Do not override first-scene severity silently. If `agent resolve` (any mode) or `agent evidence add` passes `--severity` that differs from first-scene evidence, also pass `--severity-note <why>`.
- Do not claim completion before `gh-address-cr final-gate <owner/repo> <pr_number>` has just passed and the final response includes the exact `completion_summary_line` or first bracketed line from `PR Completion Summary Guidance`.
- Do not record `--validation` without a measured timing suffix when the real duration is known. Bare `cmd=passed` yields a `TELEMETRY_TIMING_UNAVAILABLE` diagnostic and an empty `duration`/`slowest` line; use `cmd=passed@<n>ms` (or `@<n>s`).
- Do not create ad-hoc findings files in the project workspace when `findings --input -` can consume producer output through stdin.
- Do not use this skill as the review engine itself; it manages intake, state, processing discipline, and gating.
- Do not rely on `agents/openai.yaml` for unique behavior; it is only a thin assistant-specific hint layer.

## Required Facts

`review-to-findings` does not accept arbitrary Markdown. It only accepts the fixed `finding` block format. This converter rejects plain narrative Markdown review output.

For GitHub review threads, reply and resolve are both mandatory. A GitHub thread is not terminally clean unless reply evidence exists with a concrete reply URL from the current authenticated GitHub login.

`producer=code-review` must emit findings JSON before session handling starts. Local findings become terminal only with a note and required evidence.

Source-scoped `findings` ingestion is a session handoff edge. After it succeeds, rerun `review <owner/repo> <pr_number>` to continue GitHub thread handling and final-gate work.

## Reference Surface

The reference surface is intentionally split so this file stays a first-read entrypoint.

- State machine index: `references/status-action-map.md`
- Agent protocol details: `references/agent-protocol.md`
- Completion contract: `references/completion-contract.md`
- Feedback issue workflow: `references/feedback.md` — filing a `tooling-bug` feedback is an expected automatic step when a command crashes or returns an `_ERROR` reason_code (not for normal `*_REJECTED`/`WAITING_*`/input rejections)
- Dispatch details: `references/mode-producer-matrix.md`
- Review triage checklist: `references/cr-triage-checklist.md`
- Evidence ledger expectations: `references/evidence-ledger.md`
- OTel trace export and opt-out controls: `references/otel-worker-better-stack.md`

Low-level implementation details are inside the `gh-address-cr` runtime package, not the public agent surface.
