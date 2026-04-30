# gh-address-cr skill

An auditable PR-session workflow skill and runtime CLI for AI coding agents.

Project architecture governance lives in `.specify/memory/constitution.md`.
The installed skill contract remains `skill/SKILL.md`; keep
repo-root governance and packaged-skill instructions in their own scopes.

It now treats a Pull Request as the session root and can ingest both:

- GitHub review threads
- local AI-agent review findings

Both become session items that move through one evidence-first workflow with a final gate.
For handled GitHub threads, replying and resolving are still two separate required operations.
`final-gate` now also verifies that every terminal GitHub thread has durable reply evidence, not only that unresolved-thread count reached zero.

## Runtime / Skill Split

The deterministic implementation belongs to the runtime package:

- console entrypoint: `gh-address-cr`
- module entrypoint: `python3 -m gh_address_cr`
- source package: `src/gh_address_cr/`

The packaged skill remains under `skill/` and acts as a thin adapter:

- `skill/SKILL.md` explains agent behavior
- `skill/scripts/cli.py` is a compatibility shim
- `skill/runtime-requirements.json` declares runtime compatibility
- `skill/agents/` and `skill/references/` provide hints and reference docs

The shim must delegate to the runtime or fail loudly before mutating session state. Runtime state machines, leases, GitHub side effects, evidence ledgers, and final-gate behavior must not be reimplemented as skill-owned workflow code.

## Installation

### Install the released runtime CLI

Use this path when you want the stable `gh-address-cr` executable from PyPI. The runtime CLI requires Python 3.10 or newer.

```bash
pipx install gh-address-cr
gh-address-cr --help
python -m gh_address_cr --help
```

The `uv` equivalent is:

```bash
uv tool install gh-address-cr
gh-address-cr --help
python -m gh_address_cr --help
```

These commands install the Python runtime package. They do not install or update the packaged skill adapter under `skill/`.

### GitHub-direct runtime validation install

Use this path only for pre-release validation of the current repository state before a PyPI release is available.

```bash
pipx install git+https://github.com/RbBtSn0w/gh-address-cr.git
gh-address-cr --help
gh-address-cr agent manifest
```

The `uv` equivalent is:

```bash
uv tool install git+https://github.com/RbBtSn0w/gh-address-cr.git
gh-address-cr --help
gh-address-cr agent manifest
```

### Local editable development install

Use this path when editing this repository.

```bash
python3 -m pip install -e .
gh-address-cr --help
python3 -m gh_address_cr --help
gh-address-cr agent manifest
```

### Packaged skill install

Use this path when installing the Codex/agent skill adapter. This does not install the runtime CLI package; install the runtime separately with `pipx`, `uv tool`, GitHub-direct validation, or local editable development commands above.

```bash
npx skills add https://github.com/RbBtSn0w/gh-address-cr --skill skill
npx skills check
```

After installing the skill, verify that a runtime CLI is available:

```bash
gh-address-cr --help
python3 skill/scripts/cli.py adapter check-runtime
```

### Upgrade from skill-shim usage

If you previously relied on `python3 skill/scripts/cli.py` from the packaged skill compatibility shim, reinstall the runtime CLI with `pipx` or `uv tool` instead of reinstalling the skill as a substitute:

```bash
pipx reinstall gh-address-cr
# or
uv tool upgrade gh-address-cr
```

Then verify:

```bash
gh-address-cr --help
gh-address-cr agent manifest
```

If PyPI does not yet contain `gh-address-cr`, use the GitHub-direct runtime validation install until a release is published.

Runtime install for local development:

```bash
python3 -m pip install -e .
gh-address-cr --help
python3 -m gh_address_cr --help
python3 skill/scripts/cli.py adapter check-runtime
```

Native runtime ownership is now split by responsibility:

- `src/gh_address_cr/core/session.py`: PR-scoped session loading, saving, and workspace paths
- `src/gh_address_cr/core/workflow.py`: agent classification, leases, action requests, accepted responses, and deterministic publishing transitions
- `src/gh_address_cr/core/gate.py`: final-gate policy evaluation and the native `Gatekeeper`
- `src/gh_address_cr/github/client.py`: GitHub CLI IO for thread listing, replies, resolves, and pending reviews
- `src/gh_address_cr/intake/findings.py`: findings parsing, normalization, source-scoped fingerprints, and fixed finding blocks
- `src/gh_address_cr/legacy_scripts/`: compatibility shims for packaged runtime script paths

The native packages under `core/`, `github/`, and `intake/` must not import `legacy_scripts`.
Public high-level commands (`review`, `address`, `threads`, `findings`, and `adapter`) are routed through the native runtime package. Core script entrypoints such as `session_engine.py`, `cr_loop.py`, and `control_plane.py` now delegate to native modules; the remaining `legacy_scripts` files are compatibility surfaces for older direct script invocations.

## Public Interface

`gh-address-cr` should be understood first as a PR-scoped workflow orchestrator with one public main entrypoint plus a lightweight thread-only shortcut:

- `review`
- `address`

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
- `agent publish`
- `agent leases`
- `agent reclaim`
- `final-gate`

Fail-fast contract:

- `review` does not bind to any one review skill or tool name.
- `review` is the public main entrypoint.
- If findings are absent, `review` returns `WAITING_FOR_EXTERNAL_REVIEW` and writes a standard producer handoff request instead of waiting on `stdin`.
- External producer output must be findings JSON or fixed `finding` blocks.
- `findings` still requires explicit findings JSON input.
- `review-to-findings` does not accept arbitrary Markdown. It only accepts the fixed `finding` block format.
- `review`, `threads`, and `adapter` also fail immediately when `gh` is missing from `PATH`.
- For `adapter`, wrapper `--human` and `--machine` belong before `adapter`. Arguments after `<adapter_cmd...>` are passed through to the adapter command unchanged.
- The high-level CLI commands are the agent-safe public surface. Treat low-level scripts as implementation details.

`review` is the default orchestrator. It either:

- consumes explicit findings input when `--input` is supplied, or
- generates an external review handoff and waits for a producer-compatible result

High-level entrypoints emit machine-readable JSON summaries by default. Use `--human` when a person needs narrative text. `--machine` remains a compatibility alias.

Minimal invocation model:

```text
/gh-address-cr review <owner/repo> <pr_number>
/gh-address-cr address <owner/repo> <pr_number>
```

Advanced/internal integrations are documented later in this README.

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
- `exit_code`
- `diagnostics` (optional, for GitHub CLI/API failures)

`reason_code` is the stable machine reason. `waiting_on` is the stable wait-state category.
`counts.*` may be `null` in preflight wait/fail states before GitHub or session scans run.
When present, `diagnostics` includes the underlying `gh` command, `returncode`, `stderr_category` (`auth`, `network`, `sandbox`, `environment`, `rate_limit`, `not_found`, `api`, or `unknown`), and a bounded redacted `stderr_excerpt`.
The `threads` command and lightweight address states may also include a `threads` array with actionable thread context for agents: `thread_id`, `path`, `line`, `body`, `url`, state/status, reply evidence, and accepted-response presence.

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
gh-address-cr agent submit-batch owner/repo 123 --input batch-response.json
gh-address-cr agent publish owner/repo 123
gh-address-cr agent leases owner/repo 123
gh-address-cr agent reclaim owner/repo 123
gh-address-cr agent orchestrate {start,step,status,stop,resume,submit} owner/repo 123
gh-address-cr final-gate owner/repo 123
```

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
Use `agent submit-batch` only for GitHub review-thread `fix` evidence when one commit/files/validation set addresses multiple leased threads. The batch payload still references each thread's issued `request_id` and `lease_id`, and each item supplies its own `summary`/`why`; the runtime expands it into per-item accepted evidence before `agent publish`.

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
      "commit_hash": "abc123",
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
- rerun the same `review` command after writing one of the handoff files
- plain narrative Markdown is not accepted

Producer contract:

- `gh-address-cr` does not require a specific skill name
- it accepts output from any external review producer
- the producer may be another skill, a command, or another review tool
- the only required contract is findings JSON or fixed `finding` blocks

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

// If you are also the review producer, write findings JSON to incoming-findings.json
// or fixed `finding` blocks to incoming-findings.md now.
// Do not write a plain Markdown-only review report.

// After any external review producer fills a handoff file, rerun the same command
$gh-address-cr review <PR_URL>

// If review returns BLOCKED, inspect loop-request-*.json, apply fix/clarify/defer,
// then rerun the same review command

// Adapter wrapper output flag comes before `adapter`
python3 skill/scripts/cli.py --human adapter owner/repo 123 python3 tools/review_adapter.py

// Flags after the adapter command belong to the adapter itself
python3 skill/scripts/cli.py adapter owner/repo 123 python3 tools/review_adapter.py --base main --human
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
写入 `incoming-findings.json`；或者生成固定格式的 `finding` blocks`，
写入 `incoming-findings.md`。不要只输出普通 Markdown 审查报告。

收到 handoff 后，重新运行同一条 `review` 命令，继续处理 session、GitHub review threads、fix 和 final-gate，直到通过。
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
- 不要只输出普通 Markdown 审查报告

写入 handoff 文件后，重新运行同一条 $gh-address-cr review 命令，
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
- 不要只输出普通 Markdown 审查报告

写入 handoff 文件后，重新运行同一条 $gh-address-cr review 命令，
继续处理 session、GitHub threads、fix、reply/resolve 和 final-gate，直到通过。
```

## AI Agent Feedback

When the skill itself blocks progress, file a feedback issue in this repository instead of silently dropping the problem.

- By default, feedback issues are filed to `RbBtSn0w/gh-address-cr`. Override `--target-repo` only when the skill owner explicitly directs you to use a different feedback repository.
- Use feedback issues for skill-level problems such as contradictory instructions, missing automation, documentation gaps, or repeatable tooling failures that are not caused by the repository under review.
- Do not file feedback issues for normal PR findings, target-repository bugs, or expected wait states such as `WAITING_FOR_EXTERNAL_REVIEW`.
- Do not include usernames, emails, tokens, machine names, or absolute local paths in feedback issues.
- Prefer safe technical diagnostics such as failing command, exit code, status, `reason_code`, `waiting_on`, `run_id`, and skill version.
- For PR-scoped feedback, always provide `--using-repo` and `--using-pr` so the issue body names the repository and pull request under review. If they are omitted, `submit_feedback.py` will try to infer them from `--source-command` or `--failing-command`, but explicit values are preferred.
- When `--using-repo` and `--using-pr` are provided, the helper auto-collects the latest local evidence from the PR workspace when available:
  - `last-machine-summary.json`
  - `session.json`
  - `audit_summary.md`
  - cached PR head SHA from `github_pr_cache.json`
- The helper deduplicates repeated reports by fingerprint and skips creating a new issue when the same feedback issue is already open or was closed recently within the cooldown window.
- The repository issue format lives in `.github/ISSUE_TEMPLATE/ai-agent-feedback.md`.
- Repository-root helper command:

```bash
python3 skill/scripts/submit_feedback.py \
  --category workflow-gap \
  --title "blocked without a recovery step" \
  --summary "review stopped in a blocked state without enough operator guidance." \
  --expected "the skill should identify the next command or artifact to inspect." \
  --actual "the workflow stopped and the next action was ambiguous." \
  --source-command "python3 skill/scripts/cli.py review owner/repo 123" \
  --failing-command "python3 skill/scripts/cli.py final-gate owner/repo 123" \
  --exit-code 5 \
  --status BLOCKED \
  --reason-code WAITING_FOR_FIX \
  --waiting-on human_fix \
  --run-id cr-loop-20260417T120000Z \
  --skill-version 1.2.0 \
  --using-repo owner/repo \
  --using-pr 123 \
  --artifact /tmp/loop-request.json
```

- Unified CLI passthrough:

```bash
python3 skill/scripts/cli.py submit-feedback --category workflow-gap --title "..." --summary "..." --expected "..." --actual "..."
```

## Choosing Fixes

`gh-address-cr` is not "fix every comment immediately". The intended workflow is:

1. verify the claim in current HEAD
2. classify it as `fix`, `clarify`, `defer`, or `reject`
3. only modify code after the item is confirmed and in scope

Use these defaults:

- `fix`
  - correctness bugs
  - session/gate/loop mismatches
  - concurrency or state hazards
  - CLI or wrapper compatibility regressions
  - packaging/runtime/CI breakage
- `clarify`
  - reviewer misunderstood current behavior
- `defer`
  - issue is real but would expand the PR into a larger redesign
- `reject`
  - suggestion is technically incorrect or would violate an intentional contract

Do not stretch the PR just to silence a thread. If the item is valid but not appropriate for the current scope, defer it with a concrete rationale.

## Advanced / Developer Integration

The public user flow above does not require manual `--input`, producer selection, or mode routing.
The following commands remain available for explicit integrations, repository-root automation, and debugging.

`findings --sync` requires an explicit `--source` so missing local findings stay scoped to one producer.

For explicit automation or repository-root invocation, the main command is:

```bash
python3 skill/scripts/cli.py review <owner/repo> <pr_number> [--input <path>|-] [--human]
python3 skill/scripts/cli.py address <owner/repo> <pr_number> [--human]
```

For `producer=code-review`, generate the standardized bridge prompt with:

```bash
python3 skill/scripts/cli.py prepare-code-review <local|mixed> <owner/repo> <pr_number>
```

This does not run another skill by itself. It emits the exact findings contract and ingest target so a local review producer can feed `gh-address-cr` without prompt drift.

If the upstream review output is Markdown review blocks, convert it first with:

```bash
python3 skill/scripts/cli.py review-to-findings <owner/repo> <pr_number> --input -
```

The converter writes the standardized findings JSON to the cache-backed PR workspace by default and also prints the JSON to stdout.

Advanced CLI examples:

```text
$gh-address-cr address <PR_URL>
$gh-address-cr review --auto-simple <PR_URL>
$gh-address-cr threads <PR_URL>
$gh-address-cr findings <PR_URL> --input findings.json
$gh-address-cr findings <PR_URL> --input - --sync
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
    - `commit_hash`
    - `files`
    - optional `severity`, `why`, `test_command`, `test_result`
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
python3 skill/scripts/cli.py adapter owner/repo 123 python3 tools/review_adapter.py
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
python3 skill/scripts/cli.py review <owner/repo> <pr_number> [--input <path>|-] [--human]
```

## Core Workflow

```text
       [ Start PR Review Session ]
                   |
                   v
+-------------------------------------+      (Fetch PR threads, exclude handled)
|          1. python3 skill/scripts/cli.py run-once             | <-----------------------------------------+
+------------------+------------------+                                           |
                   |                                                              |
                   v [Generates Snapshot, Syncs Session, Lists Work]              |
                   |                                                              |
+------------------+------------------+      (THE "BRAIN" STEP: Analyze & Decide) |
|    2. Analysis & Decision Matrix    |                                           |
+------------------+------------------+                                           |
                   |                                                              |
         +---------+---------+-----------------------+                            |
         |                   |                       |                            |
    [ ACCEPT ]          [ CLARIFY ]             [ DEFER ]                         |
   (Bug/Logic)        (Misunderstood)       (High-cost Nit)                       |
         |                   |                       |                            |
         v                   v                       v                            |
+--------+--------+ +--------+--------+     +--------+--------+                   |
| 3a. Change Code | | 3b. Explain     |     | 3c. Explain     |                   |
|     & Test      | |     Logic       |     |     Trade-offs  |                   |
+--------+--------+ +--------+--------+     +--------+--------+                   |
         |                   |                       |                            |
         v                   v                       v                            |
+--------+--------+ +--------+--------+     +--------+--------+                   |
| 4a. generate_   | | 4b. generate_   |     | 4c. generate_   |                   |
|    reply     | |    reply     |     |    reply     |                   |
|    --mode fix   | |  --mode clarify |     |   --mode defer  |                   |
+--------+--------+ +--------+--------+     +--------+--------+                   |
         |                   |                       |                            |
         +---------+---------+-----------------------+                            |
                   |                                                              |
                   v [Generates reply markdown in the PR workspace]               |
                   |                                                              |
+------------------+------------------+      (GitHub API: Reply)                  |
|         5. python3 skill/scripts/cli.py post-reply            |                                           |
+------------------+------------------+                                           |
                   |                                                              |
+------------------+------------------+      (MANDATORY for all paths)            |
|       6. python3 skill/scripts/cli.py resolve-thread          |      (Local state marked 'Handled')       |
+------------------+------------------+                                           |
                   |                                                              |
+------------------+------------------+      (HARD GATE: Re-fetch GitHub state)   |
|         7. python3 skill/scripts/cli.py final-gate            |-------------------------------------------+
+------------------+------------------+      [ Failed: Unresolved > 0 (Loop back) ]
                   |
                   | [ Passed: Unresolved == 0 ]
                   v
+-------------------------------------+
|         8. Audit Summary            |      (Output SHA256 & Final Confirmation)
+-------------------------------------+
                   |
                   v
               [ Done ]
```

## PR Session Architecture

`gh-address-cr` now ships a session engine at `skill/scripts/session_engine.py`.

The implementation model is now:

- Python owns the stateful logic and GitHub/local-review orchestration.
- `python3 skill/scripts/cli.py` is the only automation entrypoint; internal commands use the Python CLI directly.
- `skill/scripts/cli.py` is the unified Python dispatcher for the main command set.
- Tests are organized around Python behavior first, then CLI syntax compatibility.

- `github_thread` items are synced from GraphQL thread snapshots.
- `local_finding` items are ingested from a local review adapter.
- local findings can now be explicitly closed in-session with `session_engine.py close-item`.
- `python3 skill/scripts/cli.py final-gate` evaluates both:
  - session blocking item count
  - unresolved GitHub thread count
  - terminal GitHub thread reply-evidence count
  - current-login pending review count

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

If `python3 skill/scripts/cli.py final-gate --auto-clean` passes, the current PR workspace is archived before deletion under:

- archive root: `archive/<owner>__<repo>/pr-<pr>/<run_id>/`

To inspect one run after the fact, use:

```bash
python3 skill/scripts/audit_report.py --run-id <run_id> <owner/repo> <pr_number>
```

The session also tracks loop-safety metadata per item:

- `repeat_count`: how many times the same local finding was re-ingested
- `reopen_count`: how many times a previously closed/deferred/clarified item was reopened
- claim lease fields so stale ownership can be reclaimed

## Optional Telemetry Export

Local audit files remain the canonical repository contract:

- `audit.jsonl`
- `trace.jsonl`
- `audit_summary.md`

The distributed CLI now ships with a zero-config hosted relay endpoint:

- `https://gh-address-cr.hamiltonsnow.workers.dev/v1/logs`

By default, each audit/trace event is also emitted as an OTLP/HTTP JSON `logs` record to that Cloudflare Worker.

Recommended deployment shape:

- CLI client
- Cloudflare Worker as the security relay
- Better Stack as the backend

This keeps the Better Stack source token out of the CLI runtime while preserving local audit artifacts for `audit-report`, archive, and tests. End users do not need to set telemetry environment variables for the hosted path.

Repository-root reference docs:

- setup guide: `skill/references/otel-worker-better-stack.md`
- Worker example: `skill/references/otel-worker-better-stack/worker.mjs`
- Wrangler example: `skill/references/otel-worker-better-stack/wrangler.example.jsonc`

For self-hosting or explicit override, CLI-side OpenTelemetry configuration still supports standard env vars:

```bash
export OTEL_SERVICE_NAME="gh-address-cr-cli"
export OTEL_RESOURCE_ATTRIBUTES="deployment.environment=personal,service.namespace=skills"
export OTEL_EXPORTER_OTLP_ENDPOINT="https://gh-address-cr-telemetry.example.workers.dev"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/json"
```

Notes:

- `OTEL_EXPORTER_OTLP_ENDPOINT` is treated as a base URL, so `/v1/logs` is appended automatically
- `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` may be used instead when you want an exact logs endpoint
- local audit files are still written even if telemetry export is disabled or fails
- export failures are recorded locally as `telemetry_export` diagnostics in `trace.jsonl`

## Local AI Review Ingestion

Use `python3 skill/scripts/cli.py run-local-review` to feed local AI findings into the PR session:

```bash
python3 skill/scripts/cli.py run-local-review --source local-agent:codex owner/repo 123 ./adapter.sh --base main --head HEAD
```

Adapter contract:

- adapter prints a JSON array to stdout
- each finding should include `title`, `body`, `path`, `line`
- optional fields: `severity`, `category`, `confidence`

This path does not auto-post to GitHub. It creates local session items that can be fixed and verified in the same workflow as remote review threads.

If the producer is a local `code-review` run, use the built-in adapter backend:

```bash
python3 skill/scripts/cli.py prepare-code-review mixed owner/repo 123
cat findings.json | python3 skill/scripts/cli.py review owner/repo 123 --input -
```

Input rule:

- if you already have a real findings JSON file from another tool, use `--input <path>`
- if findings are being produced in the current step, prefer `--input -` and pipe them over `stdin`
- do not create ad-hoc temporary findings files in the project workspace just to drive the workflow
- use `--sync` when you want missing local findings from the same source to auto-close on refresh

`prepare-code-review` now also returns:

- `workspace_dir`
- `findings_output_path`
- `reply_output_path`
- `loop_request_path`

Use that cache-backed findings path instead of creating review artifacts in the project workspace.

If your review tool already produces findings JSON, you do not need a custom adapter command. Use `python3 skill/scripts/cli.py ingest-findings` instead:

```bash
cat findings.json | python3 skill/scripts/cli.py ingest-findings --source local-agent:code-review owner/repo 123
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

To publish a local finding back to GitHub as a review comment:

```bash
python3 skill/scripts/cli.py publish-finding --repo owner/repo --pr 123 local-finding:<fingerprint>
```

To reclaim expired item claims inside a PR session:

```bash
python3 skill/scripts/session_engine.py reclaim-stale-claims owner/repo 123
```

To apply a terminal local finding resolution atomically, use:

```bash
python3 skill/scripts/session_engine.py resolve-local-item owner/repo 123 local-finding:<fingerprint> fix --note "Fixed locally and verified."
python3 skill/scripts/session_engine.py resolve-local-item owner/repo 123 local-finding:<fingerprint> clarify --note "Expected behavior."
python3 skill/scripts/session_engine.py resolve-local-item owner/repo 123 local-finding:<fingerprint> defer --note "Deferred to a follow-up PR."
```

## Python-First Script Layout

The main logic now lives in Python under `skill/scripts/`:

- `cli.py`
- `cr_loop.py`
- `code_review_adapter.py`
- `session_engine.py`
- `python_common.py`
- `run_once.py`
- `final_gate.py`
- `list_threads.py`
- `post_reply.py`
- `resolve_thread.py`
- `run_local_review.py`
- `publish_finding.py`
- `mark_handled.py`
- `audit_report.py`
- `generate_reply.py`
- `batch_resolve.py`
- `clean_state.py`

These Python entrypoints require Python 3.10+ because the implementation uses modern typing syntax such as `list[str]` and `str | None`.

The Python CLI is the stable automation surface; all internal commands use the Python CLI directly.

Unified CLI examples:

```bash
python3 skill/scripts/cli.py run-once owner/repo 123
python3 skill/scripts/cli.py final-gate --no-auto-clean owner/repo 123
python3 skill/scripts/cli.py session-engine gate owner/repo 123
python3 skill/scripts/cli.py ingest-findings --source local-agent:code-review owner/repo 123 --input findings.json
python3 skill/scripts/cli.py review owner/repo 123 --input -
python3 skill/scripts/cli.py findings owner/repo 123 --input -
python3 skill/scripts/cli.py session-engine resolve-local-item owner/repo 123 local-finding:<fingerprint> fix --note "Fixed locally."
```

## Testing

Run the current automated checks with:

```bash
python3 -m unittest discover -s tests
python3 skill/scripts/cli.py --help
python3 skill/scripts/cli.py cr-loop --help
```

Current test layout:

- `tests/test_session_engine_cli.py`
  - PR session state machine and gate behavior
- `tests/test_python_wrappers.py`
  - Python entrypoints for GitHub/local-review flows
- `tests/test_aux_scripts.py`
  - helper scripts such as reply generation, batch resolve, and state cleanup
- `tests/helpers.py`
  - shared test harness

## Install with npx skills

```bash
npx skills add https://github.com/RbBtSn0w/gh-address-cr --skill skill
```

## Breaking changes (2026-04-09)

- `python3 skill/scripts/cli.py batch-resolve` now requires an approved list format:
  - one thread per line: `APPROVED <thread_id>`
  - empty lines and `#` comments are allowed
  - raw thread-id lines now fail fast
- `python3 skill/scripts/cli.py list-threads` now uses the latest thread comment as primary context and emits:
  - `comment_source` (`latest|first|none`)
  - `first_url`, `latest_url`
  - `url`/`body` remain available, now latest-first with fallback

## Update model (official `skills` behavior)

`npx skills update` is driven by the lock file and remote folder hash, not by git tag directly.

- Lock file name: `.skill-lock.json`
- Typical path: `~/.agents/.skill-lock.json`
- Optional path when `XDG_STATE_HOME` is set: `$XDG_STATE_HOME/skills/.skill-lock.json`
- Update comparison key: `skills.<skill-name>.skillFolderHash` (GitHub tree SHA of the skill folder)

### User-side update commands

```bash
# Check whether updates are available
npx skills check

# Update installed skills
npx skills update
```

### Provider-side release policy

- Keep skill identifier stable:
  - `SKILL.md` frontmatter `name` should stay stable
  - skill folder path should stay stable
  - source repo (`owner/repo`) should stay stable
- Publish all releasable changes to `main` so `skillFolderHash` can change and be detected by `check/update`.
- Use semantic version tags + changelog for human-readable release management.

## What this skill provides

- PR-scoped session state for GitHub threads and local findings
- Strict per-item CR handling workflow
- Required evidence format (commit/files/test result)
- Mandatory final gate (`python3 skill/scripts/cli.py final-gate`) before completion
- Session-scoped state tracking to avoid duplicate work
- Audit log + trace log + audit summary + summary hash output
- Audit summaries and `final-gate` output preserve machine-readable gate counts and summary hashes for evidence
- Python-first implementation with a single CLI entrypoint
- Module-split automated tests for session, wrappers, and helper scripts

## Repository Layout Model

This git repository is the development and release wrapper around one shipped skill.

- Published skill payload: the entire `skill/` directory
- Repo-level verification harness: `tests/`
- Repo-level release and contributor files: `.github/`, `pyproject.toml`, `CHANGELOG.md`, root `AGENTS.md`, and other top-level metadata

Path convention:

- Repo-level docs and commands that are executed from repository root use paths like `skill/scripts/cli.py`
- Skill-owned docs inside `skill/` use paths relative to the skill root, such as `scripts/cli.py`, `references/...`, and `agents/openai.yaml`

If a rule or instruction must ship with the installed skill, it must live inside `skill/`, not only at repository root.

## Skill folder

- `skill/`
  - `SKILL.md`
  - `agents/openai.yaml`
  - `scripts/*.py`
  - `python3 skill/scripts/cli.py` (compat entrypoint)
  - `assets/reply-templates/*`
  - `references/cr-triage-checklist.md`

## Quick usage after installation

```bash
python3 skill/scripts/cli.py run-once --audit-id run-YYYYMMDD owner/repo 123
python3 skill/scripts/cli.py run-local-review --source local-agent:codex owner/repo 123 ./adapter.sh
python3 skill/scripts/cli.py post-reply --repo owner/repo --pr 123 --audit-id run-YYYYMMDD <thread_id> "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md"
python3 skill/scripts/cli.py resolve-thread --repo owner/repo --pr 123 --audit-id run-YYYYMMDD <thread_id>
python3 skill/scripts/cli.py submit-action <loop_request_path> --resolution fix --note "Fixed it" -- <resume_command>
python3 skill/scripts/cli.py final-gate --auto-clean --audit-id run-YYYYMMDD owner/repo 123
```

## Operating Modes

This skill supports several distinct operating modes. The session model is the same in all of them, but the required commands differ.

### Mode 1: GitHub Thread Only

Use this when the PR already has remote review threads and there is no local AI review input.

Example:

```bash
python3 skill/scripts/cli.py run-once --audit-id run-20260412 owner/repo 123

# inspect one unresolved GitHub thread
python3 skill/scripts/cli.py generate-reply --mode fix --severity P2 "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md" abc123 "src/app.py" "python3 -m unittest" "passed" "Added the missing guard."
python3 skill/scripts/cli.py post-reply --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md"
python3 skill/scripts/cli.py resolve-thread --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID

python3 skill/scripts/cli.py final-gate --auto-clean --audit-id run-20260412 owner/repo 123
```

Rules:

- GitHub thread items require both `python3 skill/scripts/cli.py post-reply` and `python3 skill/scripts/cli.py resolve-thread`
- `python3 skill/scripts/cli.py resolve-thread` rejects silent resolve attempts when reply evidence is missing
- outdated / `STALE` GitHub threads still count as unresolved until explicitly handled
- `python3 skill/scripts/cli.py final-gate` must pass before completion and now fails if a terminal GitHub thread has no reply evidence

### Mode 2: GitHub Thread Clarify / Defer

Use this when the review comment is not accepted as a code change and you need to respond with rationale.

Clarify example:

```bash
python3 skill/scripts/cli.py generate-reply --mode clarify "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md" "The current control flow is intentional because initialization must stay lazy."
python3 skill/scripts/cli.py post-reply --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md"
python3 skill/scripts/cli.py resolve-thread --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID
```

Defer example:

```bash
python3 skill/scripts/cli.py generate-reply --mode defer "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md" "This requires broader refactoring and is deferred to a follow-up PR."
python3 skill/scripts/cli.py post-reply --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md"
python3 skill/scripts/cli.py resolve-thread --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID
```

Rules:

- even without code changes, GitHub thread items still require reply plus resolve
- defer/clarify should carry rationale, not just a status change
- low-level resolve paths are intentionally blocked until reply evidence exists in the session or the same action posts a fresh reply

### Mode 3: Local Finding Only

Use this when you want to run local AI review without waiting for GitHub or Copilot review comments.

Example:

```bash
python3 skill/scripts/cli.py run-local-review --source local-agent:codex owner/repo 123 ./adapter.sh

python3 skill/scripts/session_engine.py list-items owner/repo 123 --item-kind local_finding --status OPEN
python3 skill/scripts/session_engine.py update-item owner/repo 123 local-finding:FINGERPRINT ACCEPTED --note "Confirmed locally."
python3 skill/scripts/session_engine.py update-item owner/repo 123 local-finding:FINGERPRINT FIXED --note "Implemented fix."
python3 skill/scripts/session_engine.py update-item owner/repo 123 local-finding:FINGERPRINT VERIFIED --note "Validated with targeted tests."
python3 skill/scripts/session_engine.py close-item owner/repo 123 local-finding:FINGERPRINT --note "Closed after local validation."

python3 skill/scripts/cli.py final-gate --no-auto-clean --audit-id run-20260412 owner/repo 123
```

Rules:

- local findings do not require GitHub reply/resolve unless you choose to publish them
- they still participate in the same session gate
- terminal local-item transitions require `--note`

### Mode 4: Mixed Session

Use this when the PR has both remote GitHub threads and local AI findings.

Example:

```bash
python3 skill/scripts/cli.py run-once --audit-id run-20260412 owner/repo 123
python3 skill/scripts/cli.py run-local-review --source local-agent:codex owner/repo 123 ./adapter.sh

# process GitHub items with reply + resolve
# process local items through session_engine.py transitions

python3 skill/scripts/cli.py final-gate --no-auto-clean --audit-id run-20260412 owner/repo 123
```

Rules:

- GitHub items need reply plus resolve
- local items need valid state transitions and notes
- the PR is not clear until both session blocking count and unresolved GitHub thread count are zero

### Mode 5: Publish Local Finding Back To GitHub

Use this when a locally discovered issue should become visible in the GitHub PR discussion.

Example:

```bash
python3 skill/scripts/cli.py run-local-review --source local-agent:codex owner/repo 123 ./adapter.sh
python3 skill/scripts/session_engine.py list-items owner/repo 123 --item-kind local_finding --status OPEN

python3 skill/scripts/cli.py publish-finding --repo owner/repo --pr 123 local-finding:FINGERPRINT
python3 skill/scripts/cli.py run-once --audit-id run-20260412 owner/repo 123
```

What happens:

- the local finding is published as a GitHub review comment
- later GitHub sync can associate the local finding with the resulting thread
- from that point onward, the issue can be handled like a normal GitHub review item

### Mode 6: Direct Session Engine / Unified CLI

Use this when you need low-level session control or when integrating the skill into other automation.

Examples:

```bash
python3 skill/scripts/cli.py run-once owner/repo 123
python3 skill/scripts/cli.py final-gate --no-auto-clean owner/repo 123
python3 skill/scripts/cli.py session-engine list-items owner/repo 123 --item-kind local_finding
python3 skill/scripts/cli.py session-engine reclaim-stale-claims owner/repo 123
```

Rules:

- `cli.py` is the preferred Python entrypoint for automation
- `python3 skill/scripts/cli.py` remains the stable automation surface for skill users
- low-level resolve helpers are stricter than before: `resolve-thread` and batch resolve flows refuse resolve-only handling when reply evidence is absent

## Troubleshooting final gate failure

If `python3 skill/scripts/cli.py final-gate` fails:

1. Read the pending table in terminal output and the printed audit summary path.
2. For each pending or invalid terminal thread, verify both operations were completed: `python3 skill/scripts/cli.py post-reply` and `python3 skill/scripts/cli.py resolve-thread`.
3. Re-run `python3 skill/scripts/cli.py run-once --show-all ...` to compare unresolved vs handled state.
4. If the summary reports missing reply evidence, post the reply first, then resolve the thread again before re-running `python3 skill/scripts/cli.py final-gate`.

## Troubleshooting installation and release

- Unsupported Python: use Python 3.10 or newer through `pipx`, `uv tool`, or a local virtual environment.
- Missing PyPI package: `gh-address-cr` may not have been published yet. Use the GitHub-direct runtime validation install for pre-release validation.
- Missing Trusted Publishing: production PyPI publishing must use GitHub OIDC with the PyPI project `gh-address-cr`, repository `RbBtSn0w/gh-address-cr`, workflow `.github/workflows/release.yml`, no GitHub environment constraint, and `id-token: write`.
- Stale artifact version: release-built wheel and sdist metadata must match the semantic-release version. If a publish partially succeeds, inspect PyPI before retrying because uploaded files are immutable.
- Installed smoke domain failure: `agent orchestrate status` may report a missing session and `final-gate` may report `Final gate failed to evaluate: error connecting to api.github.com` when GitHub state or network access is unavailable. These are acceptable smoke outcomes only when there is no traceback, missing import, or missing console entrypoint.
- Skill install confusion: `npx skills add ... --skill skill` installs the packaged skill adapter only. It does not install the runtime CLI package.
- Skill-shim migration confusion: if `python3 skill/scripts/cli.py` works from a checkout but `gh-address-cr` is unavailable, install or reinstall the runtime CLI with `pipx` or `uv tool`.

## CI semantic release (tag + changelog)

This repo includes a `semantic-release` workflow:

- Trigger: push to `main`
- Input: Conventional Commits history
- Output: semantic version tag (`vX.Y.Z`) + GitHub Release + `CHANGELOG.md`
- Python package release: `pyproject.toml` and `src/gh_address_cr/__init__.py` are synchronized to the semantic-release version before wheel/sdist build.
- Stable package registry: PyPI is the only documented stable runtime CLI package registry.
- GitHub Releases remain release-note, tag, source-archive, and optional provenance surfaces; they are not the primary Python package registry.
- Dry-run/staging validation: use the `workflow_dispatch` `dry-run` or `testpypi` target before enabling production PyPI publishing.
- Production PyPI publishing: requires PyPI Trusted Publishing and package-name ownership. It runs without a GitHub deployment environment approval gate; do not use long-lived PyPI API tokens unless a separate explicit release-policy change approves that fallback.
- Failed or partial publish recovery: inspect the PyPI project state and release artifacts before retrying; immutable package files may require a follow-up semantic-release version.

Commit format examples:

```text
feat: add strict unresolved-thread guard in final gate
fix: avoid duplicate handled-state writes when thread already resolved
docs: clarify npx skills update behavior
```
