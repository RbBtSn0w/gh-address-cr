---
name: gh-address-cr
description: Use when a GitHub Pull Request has unresolved review threads, pending reviews, stale/outdated threads, local findings ingestion, or needs mandatory final-gate proof in one PR-scoped session.
argument-hint: "<active-pr|review|address|threads|findings|adapter|doctor|agent|final-gate|submit-feedback> ..."
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
/gh-address-cr submit-action <action-request.json> --resolution <fix|clarify|defer|reject> ...
/gh-address-cr submit-feedback --category <category> --title <title> --summary <summary> ...
/gh-address-cr version
```

Agent protocol commands:

```text
/gh-address-cr agent manifest
/gh-address-cr agent classify <owner/repo> <pr_number> <item_id> --classification <fix|clarify|defer|reject> --note <why>
/gh-address-cr agent next <owner/repo> <pr_number> --role <role> --agent-id <id>
/gh-address-cr agent submit <owner/repo> <pr_number> --input <response.json>
/gh-address-cr agent submit-batch <owner/repo> <pr_number> --input <batch-response.json>
/gh-address-cr agent fix <owner/repo> <pr_number> <item_id> --commit <sha> --files <paths> --summary <text> --why <text> --validation <cmd=passed>
/gh-address-cr agent fix-all <owner/repo> <pr_number> --input <batch-response.json>
/gh-address-cr agent fix-all <owner/repo> <pr_number> --commit <sha> --files <paths> --validation <cmd=passed> --homogeneous-reason <why>
/gh-address-cr agent resolve-stale <owner/repo> <pr_number> --commit <sha> --files <paths> --validation <cmd=passed> --match-files
/gh-address-cr agent evidence add <owner/repo> <pr_number> --name <profile> --commit <sha> --files <paths> --validation <cmd=passed>
/gh-address-cr agent publish <owner/repo> <pr_number>
/gh-address-cr agent leases <owner/repo> <pr_number>
/gh-address-cr agent reclaim <owner/repo> <pr_number>
/gh-address-cr agent orchestrate <start|step|status|stop|resume|submit> ...
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

GitHub review comment reply tasks must be submitted to the runtime before they can be published. Draft the reply content inside an `ActionResponse` or `BatchActionResponse`, submit it with `gh-address-cr agent submit` or `gh-address-cr agent submit-batch`, then run `gh-address-cr agent publish <owner/repo> <pr_number>` so the runtime records reply evidence and resolves the thread safely. For shared commit/files/validation evidence, keep per-thread summary/why entries in the batch; use `agent fix-all --homogeneous-reason <why>` only for a homogeneous repeated concern.

If an external producer result is already available, `findings --input <path>|- --source <producer> [--sync]` may satisfy the same PR session handoff as `incoming-findings.json`. A successful ingest records the producer result in session state; `[]` is an explicit empty result, while empty stdin is not.

## Common Mistakes

- Do not infer state from human prose or logs. Use only structured machine fields and the status-action map.
- Do not post GitHub replies or resolve review threads directly. The runtime records evidence and performs deterministic side effects.
- Do not treat `STALE` or outdated GitHub threads as clean. Outdated / `STALE` GitHub threads are still unresolved until explicitly handled.
- Do not invent severity. Only explicit `P0`, `P1`, `P2`, `P3`, or `P4` evidence from the producer payload or the original GitHub review-thread comment should become session severity. Leave unknown severity unknown; reviewer `high/medium/low priority` text is raw priority evidence, not a P-scale mapping. Published fix replies should surface exactly one canonical `Review signal:` line for either trusted P-scale severity or raw reviewer priority, and omit the line when neither signal is present.
- Do not override first-scene severity silently. If `agent fix`, `agent fix-all`, `agent resolve-stale`, or `agent evidence add` passes `--severity` that differs from first-scene evidence, also pass `--severity-note <why>`.
- Do not claim completion before `gh-address-cr final-gate <owner/repo> <pr_number>` has just passed.
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
- Feedback issue workflow: `references/feedback.md`
- Dispatch details: `references/mode-producer-matrix.md`
- Review triage checklist: `references/cr-triage-checklist.md`
- Evidence ledger expectations: `references/evidence-ledger.md`
- Optional OTel -> Worker -> Better Stack logging: `references/otel-worker-better-stack.md`

Low-level implementation details are inside the `gh-address-cr` runtime package, not the public agent surface.
