# Workflows

## Review Handoff Prompts

Minimal user prompt:

```text
使用 $gh-address-cr 完整处理这个 PR：<PR_URL>
```

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

By default, the skill stores its PR progress and audit artifacts in a user cache
directory, which can be overridden with `GH_ADDRESS_CR_STATE_DIR`. If the cache
is purged, the workflow can be rebuilt from GitHub thread state; the main
downside is potential repeated work.

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

The exact dispatch behavior for each supported `mode + producer` combination is documented in `skill/references/mode-producer-matrix.md`.


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

If your review tool already produces findings JSON, you do not need a custom adapter command:

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

To record fix evidence for a local finding inside the PR session:

```bash
gh-address-cr agent fix owner/repo 123 local-finding:<fingerprint> --commit <sha> --files src/example.py --summary "Fixed locally." --why "Confirmed locally." --validation "python3 -m unittest=passed"
gh-address-cr final-gate --no-auto-clean owner/repo 123
```

## Core Workflow

```text
       [ Start PR Review Session ]
                   |
                   v
+-------------------------------------+      (Fetch PR threads, sync session)
| 1. gh-address-cr address or gh-address-cr review | <---------------------------------------+
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
| 4a. agent       | | 4b. submit-    |     | 4c. submit-    |                   |
|     fix/submit  | |     action     |     |     action     |                   |
|     evidence    | |     clarify    |     |     defer      |                   |
+--------+--------+ +--------+--------+     +--------+--------+                   |
         |                   |                       |                            |
         +---------+---------+-----------------------+                            |
                   |                                                              |
                   v [Generates reply markdown in the PR workspace]               |
                   |                                                              |
+------------------+------------------+      (GitHub API: Reply + Resolve)        |
|         5. gh-address-cr agent publish         |                                           |
+------------------+------------------+                                           |
                   |                                                              |
+------------------+------------------+      (HARD GATE: Re-fetch GitHub state)   |
|         7. gh-address-cr final-gate            |-------------------------------------------+
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


## Quick usage after installation

```bash
gh-address-cr review owner/repo 123
gh-address-cr adapter owner/repo 123 ./adapter.sh
gh-address-cr submit-action <loop_request_path> --resolution fix --note "Fixed it" -- <resume_command>
gh-address-cr submit-action <action-request.json> --agent-id codex-fixer-1 --resolution fix --note "Fixed it" --files src/example.py --validation-cmd "python3 -m unittest tests.test_example=passed"
gh-address-cr final-gate --auto-clean --audit-id run-YYYYMMDD owner/repo 123
```


## Operating Modes

This skill supports several distinct operating modes. The session model is the same in all of them, but the required commands differ.

### Mode 1: GitHub Thread Only

Use this when the PR already has remote review threads and there is no local AI review input.

Example:

```bash
gh-address-cr address owner/repo 123 --lean

# inspect one unresolved GitHub thread
gh-address-cr agent fix owner/repo 123 github-thread:THREAD_ID --commit abc123 --files src/app.py --summary "Added the missing guard." --why "Accepted reviewer finding." --validation "python3 -m unittest=passed" --severity P2
gh-address-cr agent publish owner/repo 123

gh-address-cr final-gate --auto-clean --audit-id run-20260412 owner/repo 123
```

Rules:

- GitHub thread items require both a submitted response and `gh-address-cr agent publish`
- `gh-address-cr agent publish` records reply evidence before resolving handled threads
- outdated / `STALE` GitHub threads still count as unresolved until explicitly handled
- `gh-address-cr final-gate` must pass before completion and now fails if a terminal GitHub thread has no reply evidence

### Mode 2: GitHub Thread Clarify / Defer

Use this when the review comment is not accepted as a code change and you need to respond with rationale.

Clarify example:

```bash
gh-address-cr submit-action <action-request.json> --resolution clarify --note "Initialization must stay lazy." --reply-markdown "The current control flow is intentional because initialization must stay lazy."
gh-address-cr agent submit owner/repo 123 --input <action-response.json>
gh-address-cr agent publish owner/repo 123
```

Defer example:

```bash
gh-address-cr submit-action <action-request.json> --resolution defer --note "Deferred to a follow-up PR." --reply-markdown "This requires broader refactoring and is deferred to a follow-up PR."
gh-address-cr agent submit owner/repo 123 --input <action-response.json>
gh-address-cr agent publish owner/repo 123
```

Rules:

- even without code changes, GitHub thread items still require reply plus resolve
- defer/clarify should carry rationale, not just a status change
- `submit-action` output must be submitted back to the session before `agent publish`
- low-level resolve paths are intentionally blocked until reply evidence exists in the session or the same action posts a fresh reply

### Mode 3: Local Finding Only

Use this when you want to run local AI review without waiting for GitHub or Copilot review comments.

Example:

```bash
./adapter.sh --base main --head HEAD | gh-address-cr findings owner/repo 123 --input - --sync --source local-agent:codex

gh-address-cr agent next owner/repo 123 --role fixer --agent-id codex-fixer-1
gh-address-cr agent fix owner/repo 123 local-finding:FINGERPRINT --commit <sha> --files src/example.py --summary "Implemented fix." --why "Confirmed locally." --validation "python3 -m unittest=passed"

gh-address-cr final-gate --no-auto-clean --audit-id run-20260412 owner/repo 123
```

Rules:

- local findings do not require GitHub reply/resolve unless you choose to publish them
- they still participate in the same session gate
- terminal local-item transitions require `--note`

### Mode 4: Mixed Session

Use this when the PR has both remote GitHub threads and local AI findings.

Example:

```bash
gh-address-cr review owner/repo 123
gh-address-cr adapter owner/repo 123 ./adapter.sh

# process GitHub items with reply + resolve
# process local items through gh-address-cr agent transitions

gh-address-cr final-gate --no-auto-clean --audit-id run-20260412 owner/repo 123
```

Rules:

- GitHub items need reply plus resolve
- local items need valid state transitions and notes
- the PR is not clear until both session blocking count and unresolved GitHub thread count are zero

### Mode 5: Handle Local Finding In Session

Use this when a locally discovered issue should be fixed and closed inside the PR session.

Example:

```bash
gh-address-cr adapter owner/repo 123 ./adapter.sh
gh-address-cr agent next owner/repo 123 --role fixer --agent-id codex-fixer-1

gh-address-cr agent fix owner/repo 123 local-finding:FINGERPRINT --commit <sha> --files src/example.py --summary "Fixed local finding." --why "Confirmed locally." --validation "python3 -m unittest=passed"
gh-address-cr final-gate --no-auto-clean owner/repo 123
```

What happens:

- the local finding is recorded with fix evidence in the PR session
- no GitHub review reply is posted for local-only findings
- `agent publish` is reserved for accepted GitHub review-thread responses

### Mode 6: Direct Session Engine / Unified CLI

Use this when you need low-level session control or when integrating the skill into other automation.

Examples:

```bash
gh-address-cr review owner/repo 123
gh-address-cr address owner/repo 123 --lean
gh-address-cr final-gate --no-auto-clean owner/repo 123
gh-address-cr agent leases owner/repo 123
gh-address-cr agent reclaim owner/repo 123
```

Rules:

- `gh-address-cr` is the preferred and stable automation entrypoint
- `gh-address-cr agent publish` records reply evidence before resolving handled GitHub threads
