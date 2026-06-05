# CLI Reference

## Public Interface

`gh-address-cr` should be understood first as a PR-scoped workflow orchestrator.

Primary commands:

- `active-pr`
- `review`
- `address`
- `final-gate`

Advanced/internal integration entrypoints:

- `threads`
- `findings`
- `adapter`
- `review-to-findings`
- `agent manifest`
- `agent classify`
- `agent next`
- `agent submit`
- `agent submit-batch`
- `agent fix`
- `agent fix-all`
- `agent resolve-stale`
- `agent evidence`
- `agent publish`
- `agent leases`
- `agent reclaim`

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

Minimal invocation model:

```text
/gh-address-cr active-pr [--repo <owner/repo>] [--head <branch>]
/gh-address-cr review <owner/repo> <pr_number>
/gh-address-cr address <owner/repo> <pr_number> --lean
```

Advanced/internal integrations are documented later in this reference.

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
`commands` contains executable templates for common next steps such as `address --lean`, `agent publish`, `agent fix-all`, `agent resolve-stale`, and `final-gate`.
The `threads` command and lightweight address states may also include a `threads` array with actionable thread context for agents. Full output includes `thread_id`, `path`, `line`, `body`, `url`, state/status, reply evidence, and accepted-response presence. Lean output keeps only `item_id`, `thread_id`, `path`, `line`, `state`, `status`, `is_resolved`, `is_outdated`, `claimable`, `accepted_response_present`, and `reply_evidence_present`.

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
gh-address-cr agent submit owner/repo 123 --input action-response.json
gh-address-cr agent submit owner/repo 123 --input action-response.json --publish
gh-address-cr agent submit-batch owner/repo 123 --input batch-response.json
gh-address-cr agent evidence add owner/repo 123 --name local-verified --commit <sha> --files src/example.py --validation "python3 -m unittest tests.test_example=passed" [--severity P0|P1|P2|P3|P4 --severity-note <why>]
gh-address-cr agent fix owner/repo 123 github-thread:THREAD_ID --commit <sha> --files src/example.py --summary "Fixed it." --why "The guarded path covers the review case." --validation "python3 -m unittest tests.test_example=passed" [--severity P0|P1|P2|P3|P4 --severity-note <why>] --publish
gh-address-cr agent fix-all owner/repo 123 --input batch-response.json
gh-address-cr agent fix-all owner/repo 123 --commit <sha> --files src/shared.py --validation "python3 -m unittest tests.test_shared=passed" --homogeneous-reason "Repeated same-file thread concern." [--severity P0|P1|P2|P3|P4 --severity-note <why>]
gh-address-cr agent resolve-stale owner/repo 123 --commit <sha> --files src/stale.py --validation "python3 -m unittest tests.test_stale=passed" --match-files
gh-address-cr agent publish owner/repo 123
gh-address-cr agent leases owner/repo 123
gh-address-cr agent reclaim owner/repo 123
gh-address-cr agent orchestrate {start,step,status,stop,resume,submit} owner/repo 123
gh-address-cr doctor owner/repo 123
gh-address-cr final-gate owner/repo 123
```

Classification and resolution are deliberately separate protocol phases:

- `agent classify` records triage evidence on the item before a mutating fixer lease exists. If `agent next --role fixer` returns `MISSING_CLASSIFICATION`, run `agent classify ... --classification <fix|clarify|defer|reject> --note <why>` first.
- `agent submit` consumes a fixer or verifier `ActionResponse`. Its `resolution` field is the response decision for an already leased request. If submit returns `MISSING_RESOLUTION`, add `"resolution": "fix|clarify|defer|reject"` to the response JSON and rerun `agent submit`. Use `--publish` only for accepted GitHub review-thread fix responses when the runtime should post the reply and resolve the thread in the same command.
- Review signal is evidence-backed. The runtime preserves explicit `P0`, `P1`, `P2`, `P3`, or `P4` markers from the producer payload or the original GitHub review-thread comment. Reviewer words such as `high`, `medium`, or `low priority` are stored as raw priority evidence and are not converted to P-scale severity. Published fix replies use one canonical `Review signal:` line for either trusted P-scale severity or raw reviewer priority, and omit the line when neither signal is present.
- `agent fix`, `agent fix-all`, `agent resolve-stale`, and `agent evidence add` may pass `--severity P0|P1|P2|P3|P4` as an explicit override. If that override conflicts with first-scene severity evidence on the item, include `--severity-note <why>` or the response is rejected with `SEVERITY_OVERRIDE_NOTE_REQUIRED`.

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
Use `agent submit-batch` only for GitHub review-thread `fix` evidence when one set of files/validation evidence addresses multiple leased threads. The batch payload still references each thread's issued `request_id` and `lease_id`, and each item supplies its own `summary`/`why`; the runtime expands it into per-item accepted evidence before `agent publish`. Commit evidence is hydrated during publish instead of blocking worker submit. Use `agent fix-all --input <batch-response.json>` to route explicit per-thread batch evidence, or `agent fix-all --homogeneous-reason <why>` only when the matched threads are a homogeneous repeated concern. Use `agent resolve-stale --match-files` for matching `STALE` threads; stale synchronization is still runtime-mediated evidence and publish/final-gate work, not a direct state flip.
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

Prompt patterns:

```text
先运行 `$gh-address-cr review <PR_URL>`。

如果当前 PR 还没有 findings，`review` 应进入 `WAITING_FOR_EXTERNAL_REVIEW`，
写出 `producer-request.md`、`incoming-findings.json`、`incoming-findings.md`。

如果你自己就是外部 review producer，就在当前任务里直接生成 findings JSON，
写入 `incoming-findings.json`，或者通过 `findings --input - --source <producer>` 交给同一 PR session；或者生成固定格式的 `finding` blocks，
写入 `incoming-findings.md`。不要只输出普通 Markdown 审查报告。

收到 handoff 或 source-scoped findings ingest 成功后，重新运行同一条 `review` 命令，继续处理 session、GitHub review threads、fix 和 final-gate，直到通过。
```

Ready-to-use prompt variants:

- Short generic:

```text
使用 $gh-address-cr 完整处理这个 PR：<PR_URL>。
```

- Explicit `$code-review` producer:

```text
使用 $gh-address-cr 完整处理这个 PR：<PR_URL>。

先运行 $gh-address-cr review。
如果返回 WAITING_FOR_EXTERNAL_REVIEW，就使用 $code-review 作为外部 review producer。
按照 producer-request.md 的要求交接：
- 优先把 findings JSON 写入 incoming-findings.json
- 如果只能输出固定格式的 `finding` blocks，就写入 incoming-findings.md
- 自动化路径也可以用 `findings --input - --sync --source code-review` 交接；`[]` 表示明确的空结果
- 不要只输出普通 Markdown 审查报告

写入 handoff 文件或成功 ingest source-scoped findings 后，重新运行同一条 $gh-address-cr review 命令，
继续处理 session、GitHub threads、fix、reply/resolve 和 final-gate，直到通过。
```

- Any external review producer:

```text
使用 $gh-address-cr 完整处理这个 PR：<PR_URL>。

先运行 $gh-address-cr review。
如果返回 WAITING_FOR_EXTERNAL_REVIEW，就使用当前环境中可用的外部 review 能力完成审查。
按照 producer-request.md 的要求交接：
- 优先把 findings JSON 写入 incoming-findings.json
- 如果只能输出固定格式的 `finding` blocks，就写入 incoming-findings.md
- 自动化路径也可以用 `findings --input - --sync --source <producer>` 交接；`[]` 表示明确的空结果
- 不要只输出普通 Markdown 审查报告

写入 handoff 文件或成功 ingest source-scoped findings 后，重新运行同一条 $gh-address-cr review 命令，
继续处理 session、GitHub threads、fix、reply/resolve 和 final-gate，直到通过。
```


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

Use the prompt patterns above as the canonical templates. Do not keep a second, shorter variant with weaker rules.

If you omit the producer where it is required:

- `local` and `mixed` will fail because the dispatcher cannot infer whether you mean `json`, `code-review`, or `adapter`
- `ingest` will assume `json`
- `remote` does not accept a producer at all


## Automatic Review Workflow

`review` is the autonomous runner built on top of the existing intake and gate layers.

- It performs repeated intake, item selection, action execution, and gate evaluation internally.
- By default it uses an internal fixer handoff for the current AI agent.
- If a finding cannot be resolved automatically, the workflow writes an internal fixer request artifact into the PR cache artifacts directory and exits `BLOCKED` for the agent to handle.
- `--fixer-cmd` remains available as an advanced integration path.
- External fixer commands must read a JSON payload from stdin and return JSON:
  - `resolution`: `fix`, `clarify`, or `defer`
  - `note`
  - for GitHub thread `fix`: `fix_reply`
    - `summary`
    - `files`
    - optional `commit_hash` when known; otherwise publish hydrates commit evidence
    - optional `severity`, `severity_note`, `why`, `test_command`, `test_result`
    - `validation_commands` may be used as default validation evidence when `test_command` / `test_result` are omitted
  - for GitHub thread `clarify` or `defer`: `reply_markdown`
  - optional `validation_commands`
- `adapter` producer is re-run on each iteration.
- `json` and `code-review` producers are treated as one-shot inputs for the current review run.
- The workflow exits with one of:
  - `PASSED`
  - `NEEDS_HUMAN`
  - `BLOCKED`

Advanced external-fixer example:

```bash
gh-address-cr adapter owner/repo 123 python3 tools/review_adapter.py
```

By default, the skill stores its PR progress + audit artifacts in a user cache directory
(override with `GH_ADDRESS_CR_STATE_DIR`). If the cache is purged, the workflow can be rebuilt
from GitHub thread state; the main downside is potential repeated work.

Advanced producer categories:

- `code-review`
- `json`
- `adapter`

Producer naming rule:

- `code-review` is a producer category, not a hardcoded skill name.
- It can be backed by `/code-review`, `/code-review-aa`, `/code-review-bb`, `/code-review-cc`, or any other review step that emits structured findings JSON.
- `gh-address-cr` only cares about the findings contract, not the upstream tool name.

Producer selection rule:

- `remote`
  - no producer is needed
- `ingest`
  - producer may be omitted; default is `json`
- `local` or `mixed`
  - producer must be explicit

Use this mapping:

| Upstream situation | Producer to use |
| --- | --- |
| Only GitHub review threads | none (`remote`) |
| Existing findings JSON file | `json` |
| A review-style skill/command emits findings JSON first | `code-review` |
| A command directly prints findings JSON as its interface | `adapter` |

Important:

- `producer=code-review` is the category even if the upstream tool is named `/code-review-aa` or `/code-review-bb`.
- Do not put the upstream tool name itself into the producer slot.
- Example:
  - correct: `review <owner/repo> <pr>`
  - incorrect: `code-review-aa <owner/repo> <pr>`

Meaning:

- `remote`
  - only GitHub review threads are part of the session
- `local`
  - only locally produced findings are part of the session
- `mixed`
  - GitHub review threads and local findings are both part of the session
- `ingest`
  - import existing findings JSON into the session without running a local adapter

This keeps `gh-address-cr` as the session/gate/orchestration layer while letting different review producers feed findings into the same PR workflow.

The exact dispatch behavior for each supported `mode + producer` combination is documented in:

- `skill/references/mode-producer-matrix.md`

The preferred automation entrypoint is now:

```bash
gh-address-cr review <owner/repo> <pr_number> [--input <path>|-] [--human]
```


## Local AI Review Ingestion

Use `gh-address-cr findings --input -` to feed local AI findings into the PR session without requiring GitHub thread preflight:

```bash
./adapter.sh --base main --head HEAD | gh-address-cr findings owner/repo 123 --input - --sync --source local-agent:codex
```

Producer contract:

- the producer prints a JSON array to stdout
- each finding should include `title`, `body`, `path`, `line`
- optional fields: `severity`, `category`, `confidence`
- `severity` is accepted only when it is an explicit `P0`, `P1`, `P2`, `P3`, or `P4`; missing or non-P-scale values do not create a session severity.

This path does not auto-post to GitHub. It creates local session items that can be fixed and verified in the same workflow as remote review threads.

If the producer is a local `code-review` run, use the built-in adapter backend:

```bash
cat findings.json | gh-address-cr review owner/repo 123 --input -
```

Input rule:

- if you already have a real findings JSON file from another tool, use `--input <path>`
- if findings are being produced in the current step, prefer `--input -` and pipe them over `stdin`
- do not create ad-hoc temporary findings files in the project workspace just to drive the workflow
- use `--sync` when you want missing local findings from the same source to auto-close on refresh

When `review` returns `WAITING_FOR_EXTERNAL_REVIEW`, use the cache-backed `producer-request.md` handoff instead of creating review artifacts in the project workspace.

If your review tool already produces findings JSON, you do not need a custom adapter command. Use `gh-address-cr findings` instead:

```bash
cat findings.json | gh-address-cr findings owner/repo 123 --input - --sync --source code-review
```

Accepted input shapes:

- JSON array of finding objects
- JSON object with `findings`, `issues`, or `results`
- NDJSON, one finding object per line

Field normalization is intentionally broad so external tools can map in without a custom schema bridge:

- `path` or `file` or `filename`
- `line` or `start_line` or `position`
- `title` or `rule` or `check`
- `body` or `message` or `description`

Minimum accepted finding shape:

```json
[
  {
    "title": "Missing null guard",
    "body": "Potential null dereference.",
    "path": "src/example.py",
    "line": 12
  }
]
```

This is the long-term integration path for any local code-review tool. If it can emit structured findings JSON, `gh-address-cr` can ingest it into the PR session.

To record fix evidence for a local finding inside the PR session:

```bash
gh-address-cr agent fix owner/repo 123 local-finding:<fingerprint> --commit <sha> --files src/example.py --summary "Fixed locally." --why "Confirmed finding." --validation "python3 -m unittest=passed"
gh-address-cr final-gate --no-auto-clean owner/repo 123
```

`agent fix` records the terminal local-finding resolution. `final-gate` verifies
that no blocking local or GitHub review items remain.

To reclaim expired item claims inside a PR session:

```bash
gh-address-cr agent reclaim owner/repo 123
```

To apply a terminal local finding resolution atomically, use:

```bash
gh-address-cr submit-action <action-request.json> --resolution fix --note "Fixed locally and verified." --files src/example.py --validation-cmd "python3 -m unittest=passed"
gh-address-cr submit-action <action-request.json> --resolution clarify --note "Expected behavior." --reply-markdown "Expected behavior."
gh-address-cr submit-action <action-request.json> --resolution defer --note "Deferred to a follow-up PR." --reply-markdown "Deferred to a follow-up PR."
```
