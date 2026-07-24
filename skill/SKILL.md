---
name: gh-address-cr
description: Use when a GitHub Pull Request has unresolved review threads, pending reviews, stale/outdated threads, local findings ingestion, or needs mandatory final-gate proof in one PR-scoped session.
---

# gh-address-cr

Use this skill as the thin adapter and behavioral policy layer for the
`gh-address-cr` runtime CLI.
The runtime owns session state, intake routing, leases, GitHub side effects,
reply evidence, and completion truth.

## Primary Commands

Use the runtime help and manifest as the authoritative command inventory:

```text
gh-address-cr --help
gh-address-cr agent manifest
```

Start from one of two canonical modes:

```text
gh-address-cr review <owner/repo> <pr_number>
gh-address-cr address <owner/repo> <pr_number> --lean
```

- `review` / `完整审查`: ingest explicit structured findings and handle them
  together with GitHub review threads.
- `address` / `处理评审`: handle existing GitHub review threads without
  starting a new review producer.

If the PR number is unknown, run
`gh-address-cr active-pr [--repo <owner/repo>] [--head <branch>]`.

Compose a review producer only when the user explicitly names or supplies one:

```text
Use $gh-address-cr review PR #123 with $engineering:code-review as the findings producer.
```

Require a JSON array with `title`, `body`, `path`, and `line`; use `[]` when
clean. Do not ingest narrative Markdown. Read
`references/mode-producer-matrix.md` for the exact intake command.

## Packaging And Runtime Boundary

This file is part of the packaged `gh-address-cr` skill. All paths in this document are relative to the installed skill root.
Repository tests, CI, and release metadata are outside the packaged skill
payload.

- Runtime entrypoints: `gh-address-cr` and `python3 -m gh_address_cr`
- Runtime version: inspect `gh-address-cr version` and compare it with
  `runtime-requirements.json`
- Protocol compatibility: inspect `gh-address-cr adapter check-runtime`

If the runtime or required version is unavailable, fail before session
mutation. Do not copy runtime state-machine logic into the skill.

## Execution Ladder

1. Run the selected public main entrypoint.
2. Read only the machine summary fields `status`, `reason_code`, `waiting_on`,
   `next_action`, `commands`, and `counts`.
3. Prefer the returned `commands` templates over reconstructing commands.
4. Follow `references/status-action-map.md` until the runtime accepts evidence.
5. Submit decisions through `gh-address-cr agent resolve`; publish accepted
   GitHub-thread evidence through `gh-address-cr agent publish`.
6. Run `gh-address-cr final-gate <owner/repo> <pr_number>` last.

If `review` returns `BLOCKED`, inspect the loop request artifact, apply `fix`,
`clarify`, `defer`, or `reject` through runtime evidence, then rerun the same
`review` command.

GitHub review comment reply tasks are incomplete until the runtime accepts the
response and publishes both reply and resolve side effects. Use
`references/agent-protocol.md` for item, batch, stale, decline, evidence, and
lease-recovery command shapes.

When exactly one cached PR session exists, PR-scoped commands may omit the
target. For `NO_ACTIVE_PR_SCOPE` or `AMBIGUOUS_PR_SCOPE`, pass the target
explicitly instead of guessing.

## Completion And Telemetry

Record measured timing on every `--validation` when known:

```text
gh-address-cr agent resolve <owner/repo> <pr_number> <item_id> \
  --commit <sha> --files <paths> --summary "..." --why "..." \
  --validation "unit-tests=passed@4200ms"
gh-address-cr final-gate <owner/repo> <pr_number>
```

Completion requires a freshly passing final gate. Include its exact
`completion_summary_line` in the final response. Coverage is `complete`,
`partial`, `runtime-only`, or `unavailable`. Telemetry degradation is
diagnostic, not review-resolution failure; explain abnormal diagnostics. Read
`references/completion-contract.md` before claiming completion.

For cross-invocation correlation, keep one stable session identifier:

```text
export GH_ADDRESS_CR_CONVERSATION_ID="<stable-session-id>"
```

Process telemetry is exported by the runtime through its configured Honeycomb
relay. It is fail-open and can be disabled with `DISABLE_TELEMETRY=1` or
`DO_NOT_TRACK=1`.
Never include raw prompts, tokens, usernames, machine identifiers, or
unnecessary absolute paths.

## Common Mistakes

- Do not infer state from prose or logs; follow machine fields and returned
  commands.
- Do not post GitHub replies or resolve threads directly.
- Do not treat `STALE` or outdated threads as clean.
- Do not invent P0-P4 severity. Preserve explicit producer or reviewer
  evidence, and provide `--severity-note` for an intentional override.
- Do not omit measured validation timing when it is known.
- Do not create workspace findings files when `findings --input -` is enough.
- Do not treat `agents/openai.yaml` as a behavioral contract.

`review-to-findings` does not accept arbitrary Markdown. It only accepts fenced
`finding` blocks, and rejects plain narrative Markdown review output. Local
findings require terminal notes and validation evidence.
GitHub review threads require durable reply evidence from the current
authenticated login.

## Reference Surface

Read only the reference required by the current runtime state:

- For blocked or waiting states: `references/status-action-map.md`
- For resolve, batch, evidence, or lease details:
  `references/agent-protocol.md`
- Before reporting completion: `references/completion-contract.md`
- For producer or input routing: `references/mode-producer-matrix.md`
- Before deciding `fix`, `clarify`, `defer`, or `reject`:
  `references/cr-triage-checklist.md`
- To understand runtime-owned side-effect evidence:
  `references/evidence-ledger.md`
- When the skill itself blocks progress: `references/feedback.md`; filing a
  qualifying `tooling-bug` is an expected automatic step.
