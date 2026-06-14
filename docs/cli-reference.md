# CLI Reference

## Public Interface

`gh-address-cr` should be understood first as a PR-scoped workflow orchestrator.

Primary workflow commands:

- `active-pr`
- `review`
- `address`
- `final-gate`

Other public top-level commands:

- `threads`
- `findings`
- `adapter`
- `telemetry ingest`
- `telemetry summary`
- `command-session`
- `review-to-findings`
- `submit-action`
- `submit-feedback`
- `doctor`
- `version`

Advanced/internal integration entrypoints:

The advanced surface is split between top-level integration commands above and
the structured agent protocol commands below.

Agent protocol entrypoints:

- `agent manifest`
- `agent classify`
- `agent next`
- `agent next --batch`
- `agent submit`
- `agent resolve` (`<item_id>` | `--trivial` | `--batch --input` | `--homogeneous-reason` | `--reject`/`--clarify --match-files` | `--stale --match-files`)
- `agent evidence add`
- `agent evidence list`
- `agent publish`
- `agent leases`
- `agent reclaim`
- `agent orchestrate`

Fail-fast contract:

- `review` does not bind to any one review skill or tool name.
- `review` is the public main entrypoint.
- If findings are absent, `review` returns `WAITING_FOR_EXTERNAL_REVIEW` and writes a standard producer handoff request instead of waiting on `stdin`.
- External producer output must be findings JSON or fixed `finding` blocks.
- `findings` still requires explicit findings JSON input.
- A successful `findings --input <path>|- --source <producer>` run records a source-scoped producer result in the PR session, including empty `[]` results.
- `review-to-findings` does not accept arbitrary Markdown. It only accepts the fixed `finding` block format.
- `review`, `threads`, and `adapter` also fail immediately when `gh` is missing from `PATH`.
- For `adapter`, wrapper `--human` and `--machine` belong before `adapter`. Arguments after `<adapter_cmd...>` are passed through to the adapter command unchanged.
- The high-level CLI commands are the agent-safe public surface. Treat low-level scripts as implementation details.

`review` is the default orchestrator. It either:

- consumes explicit findings input when `--input` is supplied, or
- generates an external review handoff and waits for a producer-compatible result

High-level entrypoints emit machine-readable JSON summaries by default. Use `--human` when a person needs narrative text. `--machine` remains a compatibility alias. Use `--lean` or `--summary` with `address`, `threads`, and `review --auto-simple` when agents need low-token thread rows.

`--machine` and `--human` are global wrapper flags: place them **before** the command name (e.g. `gh-address-cr --machine final-gate <owner/repo> <pr_number>`), not after it. The same placement rule that applies to `adapter` applies to every high-level command — a trailing `gh-address-cr final-gate <owner/repo> <pr_number> --machine` is not honored as the global flag. (Default output is already machine JSON, so the explicit flag is only needed to force machine output where `--human` might otherwise be in effect.)

Minimal invocation model:

```text
/gh-address-cr active-pr [--repo <owner/repo>] [--head <branch>]
/gh-address-cr review <owner/repo> <pr_number>
/gh-address-cr address <owner/repo> <pr_number> --lean
```

Advanced/internal integrations are documented later in this reference.

## Command Topology (ASCII)

This map is the CLI coverage checklist. Every public command is either a
session producer, a session mutator, a side-effect publisher, a gate, a telemetry
observer, or an operator utility. Arrows show the intended upstream/downstream
handoff. Commands that emit a `next_action` or `commands` object must point to a
downstream command in this map.

```text
+-------------------+
| gh-address-cr CLI |
+---------+---------+
          |
          +-- active-pr
          |      |
          |      +--> address --lean
          |      +--> review
          |
          +-- review [--auto-simple]
          |      |
          |      +--> WAITING_FOR_EXTERNAL_REVIEW
          |      |      |
          |      |      +--> review-to-findings
          |      |      +--> findings --input <json|-|fixed-blocks> --source <producer>
          |      |      +--> adapter <adapter_cmd...>
          |      |      +--> review (same command, after producer handoff)
          |      |
          |      +--> WAITING_FOR_SIMPLE_ADDRESS
          |      |      |
          |      |      +--> address --lean
          |      |      +--> threads --lean
          |      |      +--> agent classify
          |      |      +--> agent next --role fixer
          |      |      +--> agent next --batch
          |      |
          |      +--> session work items
          |
          +-- address [--lean|--summary]
          |      |
          |      +--> threads [--lean|--summary]
          |      +--> agent resolve <item_id>
          |      +--> agent next --batch
          |      +--> agent resolve --batch
          |      +--> agent publish
          |
          +-- threads [--lean|--summary]
          |      |
          |      +--> agent classify
          |      +--> agent next
          |      +--> agent resolve <item_id>
          |      +--> agent resolve --stale --match-files
          |
          +-- findings --input <json|->
          |      |
          |      +--> agent classify
          |      +--> agent next
          |      +--> agent submit
          |
          +-- adapter <adapter_cmd...>
          |      |
          |      +--> findings contract
          |      +--> review/address session sync
          |
          +-- agent <subcommand>
          |      |
          |      +--> manifest
          |      |
          |      +--> classify
          |      |      |
          |      |      +--> next --role fixer
          |      |
          |      +--> next --role <role>
          |      |      |
          |      |      +--> ActionRequest
          |      |      +--> ActionResponse skeleton
          |      |      +--> submit
          |      |
          |      +--> next --batch
          |      |      |
          |      |      +--> BatchActionResponse skeleton
          |      |      +--> resolve --batch --input <batch-response.json>
          |      |
          |      +--> submit
          |      |      |
          |      |      +--> accepted evidence
          |      |      +--> publish (GitHub thread fixes)
          |      |      +--> final-gate
          |      |
          |      +--> resolve <item_id>
          |      |      |
          |      |      +--> classify + claim + submit (one unified shortcut)
          |      |      +--> publish (--publish or explicit publish)
          |      |
          |      +--> resolve --trivial
          |      |      |
          |      |      +--> narrow documentation/typo fix shortcut
          |      |      +--> publish (--publish or explicit publish)
          |      |
          |      +--> resolve --batch
          |      |      |
          |      |      +--> --input <batch-response.json> per-item accepted evidence
          |      |      +--> publish
          |      |      +--> final-gate
          |      |
          |      +--> resolve --homogeneous-reason
          |      |      |
          |      |      +--> --homogeneous-reason <why> -> homogeneous batch shortcut
          |      |      +--> PER_THREAD_EVIDENCE_REQUIRED -> next --batch
          |      |
          |      +--> resolve --reject|--clarify --match-files
          |      |      |
          |      |      +--> --homogeneous-reason <why> -> homogeneous decline (no commit)
          |      |      +--> PER_THREAD_EVIDENCE_REQUIRED -> next --batch
          |      |
          |      +--> resolve --stale --match-files
          |      |      |
          |      |      +--> stale/outdated thread evidence
          |      |      +--> publish
          |      |      +--> final-gate
          |      |
          |      +--> evidence add
          |      |      |
          |      |      +--> evidence_ref in ActionResponse or BatchActionResponse
          |      |
          |      +--> evidence list
          |      |
          |      +--> publish
          |      |      |
          |      |      +--> GitHub reply + resolve side effects
          |      |      +--> final-gate
          |      |
          |      +--> leases
          |      +--> reclaim
          |      |
          |      +--> orchestrate start
          |      +--> orchestrate step
          |      +--> orchestrate status
          |      +--> orchestrate resume
          |      +--> orchestrate stop
          |      +--> orchestrate submit
          |      +--> orchestrate autopilot
          |
          +-- final-gate [--require-checks|--require-required-checks]
          |      |
          |      +--> PASS -> completion_summary_line + audit summary
          |      +--> FAIL -> address/threads/agent publish/agent next --batch
          |
          +-- telemetry ingest
          |      |
          |      +--> telemetry summary
          |      +--> final-gate telemetry coverage
          |
          +-- telemetry summary
          |      |
          |      +--> efficiency report artifact
          |
          +-- command-session --input <operations.json|->
          |      |
          |      +--> repeated gh-address-cr operations
          |
          +-- review-to-findings --input <finding-blocks.md|->
          |      |
          |      +--> findings --input <json|->
          |
          +-- submit-action <action-request.json>
          |      |
          |      +--> generated ActionResponse
          |      +--> agent submit
          |
          +-- submit-feedback
          |      |
          |      +--> maintainer issue intake for repeatable skill/runtime gaps
          |
          +-- doctor
          |      |
          |      +--> rerun blocked command after environment repair
          |
          +-- version / --version
          |
          +-- global output flags
                 |
                 +--> --machine
                 +--> --human
```

Verification boundaries:

```text
producer output
  -> review-to-findings/findings/adapter
  -> session items
  -> agent classify
  -> agent next or agent next --batch
  -> ActionResponse or BatchActionResponse
  -> agent submit or agent resolve --batch
  -> accepted evidence
  -> agent publish (GitHub thread side effects only)
  -> final-gate
  -> completion_summary_line
```

Batch-specific verification:

```text
resolve PER_THREAD_EVIDENCE_REQUIRED
  -> commands.batch_next
  -> agent next --batch
  -> runtime-owned leases + request_id values
  -> batch-response-skeleton.json
  -> agent fills common evidence + per-item summary/why
  -> agent resolve --batch validates lease ownership and request context
  -> agent resolve --batch --input routes to the same batch evidence validation path
  -> agent publish posts replies and resolves threads
  -> final-gate verifies no unresolved threads remain
```

Stable machine summary fields:

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
- `commands`
- `exit_code`
- `completion_summary_line` (for `final-gate --machine` completion evidence)
- `completion_summary` (structured final-gate completion summary with `line`, `coverage_note`, `source_summary`, `duration_summary`, `top_operation_summary`, `issue_summary`, and `artifact_summary`)
- `diagnostics` (optional, for GitHub CLI/API failures)

`reason_code` is the stable machine reason. `waiting_on` is the stable wait-state category.
`counts.*` may be `null` in preflight wait/fail states before GitHub or session scans run.
When present, `diagnostics` includes the underlying `gh` command, `returncode`, `stderr_category` (`auth`, `network`, `sandbox`, `environment`, `rate_limit`, `not_found`, `api`, or `unknown`), and a bounded redacted `stderr_excerpt`.
`commands` contains shell-quoted executable templates for common next steps such as `address --lean`, `agent publish`, `agent resolve --batch`, `agent resolve --stale`, and `final-gate`.
The `threads` command and lightweight address states may also include a `threads` array with actionable thread context for agents. Each thread row carries a stable per-session `alias` (`T1`, `T2`, …, assigned in sorted `item_id` order) that `agent resolve` accepts in place of the long `item_id`. Full output includes `item_id`, `alias`, `thread_id`, `path`, `line`, `body`, `url`, state/status, reply evidence, and accepted-response presence. Lean output keeps only `item_id`, `alias`, `thread_id`, `path`, `line`, `state`, `status`, `is_resolved`, `is_outdated`, `claimable`, `accepted_response_present`, and `reply_evidence_present`.

### Metadata Commands

```bash
# Display version
gh-address-cr --version
# or
gh-address-cr version
```


## Multi-Agent Coordination

The runtime is the coordinator. AI agents consume structured requests and return structured evidence.

```bash
gh-address-cr agent manifest
gh-address-cr agent classify owner/repo 123 local-finding:abc --classification fix --note "Real defect."
gh-address-cr agent next owner/repo 123 --role fixer --agent-id codex-fixer-1
gh-address-cr agent next owner/repo 123 --batch --agent-id codex-fixer-1
gh-address-cr agent submit owner/repo 123 --input action-response.json
gh-address-cr agent submit owner/repo 123 --input action-response.json --publish
gh-address-cr agent evidence add owner/repo 123 --name local-verified --commit <sha> --files src/example.py --validation "python3 -m unittest tests.test_example=passed" [--severity P0|P1|P2|P3|P4 --severity-note <why>]
gh-address-cr agent evidence list owner/repo 123
gh-address-cr agent resolve owner/repo 123 github-thread:THREAD_ID --commit <sha> --files src/example.py --summary "Fixed it." --why "The guarded path covers the review case." --validation "python3 -m unittest tests.test_example=passed" [--severity P0|P1|P2|P3|P4 --severity-note <why>] --publish
gh-address-cr agent resolve owner/repo 123 github-thread:THREAD_ID --trivial --commit <sha> --files docs/example.md --summary "Fixed typo." --why "Doc-only typo." --validation "docs-only=passed" --publish
gh-address-cr agent resolve owner/repo 123 --batch --input batch-response.json
gh-address-cr agent resolve owner/repo 123 --commit <sha> --files src/shared.py --validation "python3 -m unittest tests.test_shared=passed" --homogeneous-reason "Repeated same-file thread concern." [--severity P0|P1|P2|P3|P4 --severity-note <why>]
gh-address-cr agent resolve owner/repo 123 --reject --match-files --files src/shared.py --homogeneous-reason "Same backtick nit across threads; declining as non-blocking style."
gh-address-cr agent resolve owner/repo 123 --clarify --match-files --files src/shared.py --homogeneous-reason "Same question across threads; one shared clarification."
gh-address-cr agent resolve owner/repo 123 --commit <sha> --files src/stale.py --validation "python3 -m unittest tests.test_stale=passed" --stale --match-files
gh-address-cr agent publish owner/repo 123
gh-address-cr agent leases owner/repo 123
gh-address-cr agent reclaim owner/repo 123
gh-address-cr agent orchestrate {start,step,status,stop,resume,submit,autopilot} owner/repo 123
gh-address-cr doctor owner/repo 123
gh-address-cr final-gate owner/repo 123
```

Classification and resolution are deliberately separate protocol phases:

- `agent classify` records triage evidence on the item before a mutating fixer lease exists. If `agent next --role fixer` returns `MISSING_CLASSIFICATION`, run `agent classify ... --classification <fix|clarify|defer|reject> --note <why>` first.
- `agent submit` consumes a fixer or verifier `ActionResponse`. Its `resolution` field is the response decision for an already leased request. If submit returns `MISSING_RESOLUTION`, add `"resolution": "fix|clarify|defer|reject"` to the response JSON and rerun `agent submit`. Use `--publish` only for accepted GitHub review-thread fix responses when the runtime should post the reply and resolve the thread in the same command.
- Review signal is evidence-backed. The runtime preserves explicit `P0`, `P1`, `P2`, `P3`, or `P4` markers from the producer payload or the original GitHub review-thread comment. Reviewer words such as `high`, `medium`, or `low priority` are stored as raw priority evidence and are not converted to P-scale severity. Published fix replies use one canonical `Review signal:` line for either trusted P-scale severity or raw reviewer priority, and omit the line when neither signal is present.
- `agent resolve` (any mode) and `agent evidence add` may pass `--severity P0|P1|P2|P3|P4` as an explicit override. If that override conflicts with first-scene severity evidence on the item, include `--severity-note <why>` or the response is rejected with `SEVERITY_OVERRIDE_NOTE_REQUIRED`.

Role split:

- `coordinator`: deterministic runtime CLI
- `review_producer`: external findings producer
- `triage`: classifies review items as fix/clarify/defer/reject
- `fixer`: modifies code and returns evidence
- `verifier`: validates evidence and test results
- `publisher`: deterministic runtime role for GitHub replies/resolves
- `gatekeeper`: deterministic final-gate role

Parallel work is lease-based. Independent items may be claimed concurrently, but overlapping file, item, thread, or GitHub side-effect conflict keys are rejected. AI agents must not post replies or resolve GitHub threads directly; accepted evidence is published by the runtime.
After `agent submit` returns `ACTION_ACCEPTED`, follow the returned `next_action`; GitHub-thread fixes publish through `agent publish`.
Use `agent resolve --batch` only for GitHub review-thread `fix` evidence when one set of files/validation evidence addresses multiple leased threads. The batch payload still references each thread's issued `request_id` and `lease_id`, and each item supplies its own `summary`/`why`; the runtime expands it into per-item accepted evidence before `agent publish`. Commit evidence is hydrated during publish instead of blocking worker submit. Use `agent resolve --batch --input <batch-response.json>` to route explicit per-thread batch evidence, or `agent resolve --homogeneous-reason <why>` only when the matched threads are a homogeneous repeated concern. Use `agent resolve --stale --match-files` for matching `STALE` threads; stale synchronization is still runtime-mediated evidence and publish/final-gate work, not a direct state flip. To **decline** (not fix) a repeated concern across threads — e.g. the same reviewer nit you are rejecting with one rationale — use `agent resolve --reject|--clarify --homogeneous-reason <why> --match-files`. This is symmetric with the homogeneous fix shortcut but carries no commit/validation evidence: the shared `--homogeneous-reason` becomes each thread's reply, and the same body-identity gate (`PER_THREAD_EVIDENCE_REQUIRED`) prevents declining threads that raise distinct concerns.
The default manifest advertises `max_parallel_claims: 2`. This is a lease-safety limit, not a batch-size target. The same agent may claim multiple GitHub review-thread fixer leases that overlap only by file path so one same-file patch can be submitted as common batch evidence; thread side effects remain item-scoped. For many small review-thread fixes, claim the currently allowed active leases, repair them together when one validation bundle covers them, submit a batch response, publish, then claim the next set.

Reusable evidence profiles reduce repeated commit/files/validation text across responses:

```bash
gh-address-cr agent evidence add owner/repo 123 \
  --name local-verified \
  --commit abc123 \
  --files src/example.py,tests/test_example.py \
  --validation "python3 -m unittest tests.test_example=passed"
```

Later `ActionResponse` or `BatchActionResponse.common` payloads may include `"evidence_ref": "local-verified"` and still provide per-item `note`, `summary`, and `why`.
When `--validation` is provided without an explicit `=result` suffix, the entire value is treated as the command and the result defaults to `passed`; this keeps commands with environment assignments such as `PYENV_VERSION=3.10.19 python -m unittest` intact.

`agent next` writes both `request_path` and `response_skeleton_path`. Fill the response skeleton when you need a local artifact with the correct `schema_version`, `request_id`, `lease_id`, `agent_id`, `item_id`, `resolution`, `validation_commands`, and GitHub-thread `fix_reply` shape. Required user-supplied fields are intentionally empty in the skeleton so an unedited template is rejected instead of published.

For migrated work item types, `agent next` and the written `ActionRequest` may include additive `handling_boundary` fields such as `boundary_id`, `required_evidence`, `completion_criteria`, and `terminal_failure_reasons`. Lease-related rejection payloads may include `lease_recovery` with `recovery_outcome` values `renew`, `reclaim`, `refresh_state`, `stop`, or `already_completed`. `final-gate --machine` may include `logic_validation_signals`; blocking signals prevent completion, while advisory signals are diagnostic.

Minimal `BatchActionResponse` shape:

```json
{
  "schema_version": "1.0",
  "agent_id": "codex-fixer-1",
  "resolution": "fix",
  "common": {
    "files": ["src/example.py", "tests/test_example.py"],
    "validation_commands": [
      {"command": "python3 -m unittest tests.test_example", "result": "passed"}
    ],
    "fix_reply": {
      "test_command": "python3 -m unittest tests.test_example",
      "test_result": "passed"
    }
  },
  "items": [
    {
      "request_id": "req_1",
      "lease_id": "lease_1",
      "item_id": "github-thread:THREAD_1",
      "summary": "Fixed thread 1.",
      "why": "The input is now validated before use."
    }
  ]
}
```

Manual helper path for an issued runtime `ActionRequest`:

```bash
gh-address-cr submit-action <action-request.json> \
  --agent-id codex-fixer-1 \
  --resolution fix \
  --note "Fixed the thread." \
  --commit-hash abc123 \
  --files src/example.py \
  --validation-cmd "python3 -m unittest tests.test_example=passed" \
  --output-dir /tmp/gh-address-cr-response

gh-address-cr agent submit owner/repo 123 --input <generated-action-response.json>
```

The helper also accepts older loop-request artifacts with top-level `repo` and `pr_number`, but runtime `ActionRequest` files use `repository_context.repo` and `repository_context.pr_number`. Use `--output-dir` when the runtime workspace is not writable from the current sandbox.

Main entrypoint examples:

```text
$gh-address-cr review <PR_URL>
```

High-level entrypoints:

- `review`
  - public main entrypoint
  - runs the full PR review workflow automatically
  - waits for external producer handoff when findings are absent
  - supports `--auto-simple` for the lightweight GitHub thread-only path
  - handles both local findings and GitHub review threads in one run
  - emits a machine-readable JSON summary by default
- `address`
  - lightweight GitHub thread-only entrypoint for simple PRs
  - does not wait for external review findings or ingest local findings
  - emits `WAITING_FOR_SIMPLE_ADDRESS` with an actionable request artifact when threads need agent evidence
  - the request artifact includes `claimable_item_ids`, thread rows, commands, and a `batch_response_skeleton` for leased thread evidence
- `doctor`
  - checks GitHub CLI availability/auth, viewer lookup, optional repository access, and runtime cache writeability
  - use before retrying blocked workflows with auth, network, sandbox, or cache-permission symptoms
- `threads`
  - advanced/internal: GitHub review threads only
  - emits a machine-readable JSON summary by default
- `findings`
  - advanced/internal: existing findings JSON only
  - handles local findings only; it does not process GitHub review threads
  - emits a machine-readable JSON summary by default
- `adapter`
  - advanced/internal: adapter-produced findings plus PR orchestration, including GitHub thread handling
  - emits a machine-readable JSON summary by default
- `review-to-findings`
  - advanced/internal: fixed-format finding blocks to findings JSON

Automatic external review handoff:

- `review` writes `producer-request.md` when findings are absent
- any external review producer may satisfy the handoff
- preferred handoff file: `incoming-findings.json`
- fallback handoff file: `incoming-findings.md`
- `incoming-findings.md` must contain fixed `finding` blocks
- automation may also satisfy the same session handoff with `findings --input <path>|- --source <producer> [--sync]`
- rerun the same `review` command after writing one of the handoff files
- rerun the same `review` command after a successful source-scoped `findings` ingest
- plain narrative Markdown is not accepted

Producer contract:

- `gh-address-cr` does not require a specific skill name
- it accepts output from any external review producer
- the producer may be another skill, a command, or another review tool
- the only required contract is findings JSON or fixed `finding` blocks
- `[]` is a valid explicit producer result; an empty file or empty stdin is not

Minimal user prompt:

```text
使用 $gh-address-cr 完整处理这个 PR：<PR_URL>
```

Typical flows:

```text
// Main flow: start the PR session
$gh-address-cr review <PR_URL>

// If findings are absent, `review` returns WAITING_FOR_EXTERNAL_REVIEW
// and writes:
// - producer-request.md
// - incoming-findings.json
// - incoming-findings.md

// If you are also the review producer, write findings JSON to incoming-findings.json,
// feed it through `findings --input - --source <producer>`, or write fixed
// `finding` blocks to incoming-findings.md now.
// Do not write a plain Markdown-only review report.

// After any external review producer fills a handoff file or successfully ingests
// source-scoped findings, rerun the same command
$gh-address-cr review <PR_URL>

// If review returns BLOCKED, inspect loop-request-*.json, apply fix/clarify/defer,
// then rerun the same review command

// Adapter wrapper output flag comes before `adapter`
gh-address-cr --human adapter owner/repo 123 python3 tools/review_adapter.py

// Flags after the adapter command belong to the adapter itself
gh-address-cr adapter owner/repo 123 python3 tools/review_adapter.py --base main --human
```

Minimal valid `review-to-findings` input:

````text
```finding
title: Missing null guard
path: src/example.py
line: 12
body: Potential null dereference.
```
````

This converter rejects plain narrative Markdown review output.

## Advanced / Developer Integration

The public user flow above does not require manual `--input`, producer selection, or mode routing.
The following commands remain available for explicit integrations, repository-root automation, and debugging.

`findings --sync` requires an explicit `--source` so missing local findings stay scoped to one producer. Successful `findings --input <path>|- --source <producer>` runs also record a source-scoped producer result so the next plain `review` continues the same PR session instead of returning to `WAITING_FOR_EXTERNAL_REVIEW`.

For explicit automation or repository-root invocation, the main command is:

```bash
gh-address-cr active-pr [--repo <owner/repo>] [--head <branch>]
gh-address-cr review <owner/repo> <pr_number> [--input <path>|-] [--human]
gh-address-cr address <owner/repo> <pr_number> [--human|--lean]
```

For `producer=code-review`, start with `review`. When external findings are absent, it emits `WAITING_FOR_EXTERNAL_REVIEW` and writes the standardized producer handoff to `producer-request.md`.

If the upstream review output is Markdown review blocks, convert it first with:

```bash
gh-address-cr review-to-findings <owner/repo> <pr_number> --input -
```

The converter writes the standardized findings JSON to the cache-backed PR workspace by default and also prints the JSON to stdout.

Advanced CLI examples:

```text
$gh-address-cr address <PR_URL> --lean
$gh-address-cr review --auto-simple <PR_URL>
$gh-address-cr threads <PR_URL> --lean
$gh-address-cr findings <PR_URL> --input findings.json
$gh-address-cr findings <PR_URL> --input - --sync --source <producer>
$gh-address-cr adapter <PR_URL> <adapter_cmd...>
$gh-address-cr review-to-findings <owner/repo> <pr_number> --input -
$gh-address-cr --human adapter <owner/repo> <pr_number> <adapter_cmd...>
$gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...> --human --machine
```

For `adapter`, the last two examples mean different things:

- `$gh-address-cr --human adapter ...`
  - switches the wrapper output to human-oriented text
- `$gh-address-cr adapter ... --human --machine`
  - passes `--human --machine` to the adapter command itself
  - it does not change the wrapper output mode

`code-review` intake is now adapter-backed. Once you have structured findings JSON, the intake layer routes it through the built-in adapter instead of maintaining a separate special-case ingest path.

Prompt patterns, automatic workflow details, producer categories, and local AI review ingestion are maintained in `docs/workflows.md`. Keep this file focused on command syntax and machine-readable CLI contracts.

If you omit the producer where it is required:

- `local` and `mixed` will fail because the dispatcher cannot infer whether you mean `json`, `code-review`, or `adapter`
- `ingest` will assume `json`
- `remote` does not accept a producer at all
