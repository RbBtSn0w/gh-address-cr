# gh-address-cr skill

An auditable PR-session workflow skill for AI coding agents.

It now treats a Pull Request as the session root and can ingest both:

- GitHub review threads
- local AI-agent review findings

Both become session items that move through one evidence-first workflow with a final gate.
For handled GitHub threads, replying and resolving are still two separate required operations.

## Public Interface

`gh-address-cr` should now be understood as a PR-scoped workflow orchestrator with:

- a `mode`
- an optional local-review `producer`

Recommended invocation model:

```text
/gh-address-cr review <owner/repo> <pr_number>
/gh-address-cr threads <owner/repo> <pr_number>
/gh-address-cr findings <owner/repo> <pr_number>
/gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...>
```

High-level entrypoints:

- `review`
  - default entrypoint
  - runs the full PR review workflow automatically
- `threads`
  - GitHub review threads only
- `findings`
  - existing findings JSON only
- `adapter`
  - adapter command prints findings JSON

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

- `gh-address-cr/references/mode-producer-matrix.md`
- `gh-address-cr/references/newcomer-playbook.md`

The preferred automation entrypoint is now:

```bash
python3 gh-address-cr/scripts/cli.py review <owner/repo> <pr_number> [--input <path>|-]
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

For the automatic review workflow, use:

```bash
python3 gh-address-cr/scripts/cli.py review <owner/repo> <pr_number> [--input <path>|-]
```

For `producer=code-review`, generate the standardized bridge prompt with:

```bash
python3 gh-address-cr/scripts/cli.py prepare-code-review <local|mixed> <owner/repo> <pr_number>
```

This does not run another skill by itself. It emits the exact findings contract and ingest target so a local review producer can feed `gh-address-cr` without prompt drift.

`code-review` intake is now adapter-backed. Once you have structured findings JSON, the intake layer routes it through the built-in adapter instead of maintaining a separate special-case ingest path.

## Prompt Templates

When `gh-address-cr` is the main entrypoint, use:

```text
使用 $gh-address-cr 处理这个 PR：<PR_URL>

先让上游 review producer 输出 findings JSON，不要只给 Markdown。
如果 findings 是当前步骤现产出的，优先通过 stdin 传入；只有在已经存在真实 JSON 文件时才使用 --input <path>。
然后由 $gh-address-cr 接管 session、GitHub threads 和 final-gate，直到通过。
```

When the upstream review tool must run first and `gh-address-cr` can only come second, use:

```text
先运行 <review-command> 审查这个 PR：<PR_URL>，并输出 findings JSON，不要只给 Markdown。
然后把这些 findings 交给 $gh-address-cr，使用 `review` 入口接管。
如果 findings 已经是现成文件，用 --input <path>；如果是当前步骤现产出的，优先用 --input - 通过 stdin 传入。
最后由 $gh-address-cr 负责 intake、session、reply/resolve 和 final-gate。
```

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
  - `reply_markdown` for GitHub thread items
  - optional `validation_commands`
- `adapter` producer is re-run on each iteration.
- `json` and `code-review` producers are treated as one-shot inputs for the current review run.
- The workflow exits with one of:
  - `PASSED`
  - `NEEDS_HUMAN`
  - `BLOCKED`

Advanced external-fixer example:

```bash
python3 gh-address-cr/scripts/cli.py adapter owner/repo 123 python3 tools/review_adapter.py
```

By default, the skill stores its PR progress + audit artifacts in a user cache directory
(override with `GH_ADDRESS_CR_STATE_DIR`). If the cache is purged, the workflow can be rebuilt
from GitHub thread state; the main downside is potential repeated work.

## Core Workflow

```text
       [ Start PR Review Session ]
                   |
                   v
+-------------------------------------+      (Fetch PR threads, exclude handled)
|          1. run_once.sh             | <-----------------------------------------+
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
|    reply.sh     | |    reply.sh     |     |    reply.sh     |                   |
|    --mode fix   | |  --mode clarify |     |   --mode defer  |                   |
+--------+--------+ +--------+--------+     +--------+--------+                   |
         |                   |                       |                            |
         +---------+---------+-----------------------+                            |
                   |                                                              |
                   v [Generates reply markdown in the PR workspace]               |
                   |                                                              |
+------------------+------------------+      (GitHub API: Reply)                  |
|         5. post_reply.sh            |                                           |
+------------------+------------------+                                           |
                   |                                                              |
+------------------+------------------+      (MANDATORY for all paths)            |
|       6. resolve_thread.sh          |      (Local state marked 'Handled')       |
+------------------+------------------+                                           |
                   |                                                              |
+------------------+------------------+      (HARD GATE: Re-fetch GitHub state)   |
|         7. final_gate.sh            |-------------------------------------------+
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

`gh-address-cr` now ships a session engine at `gh-address-cr/scripts/session_engine.py`.

The implementation model is now:

- Python owns the stateful logic and GitHub/local-review orchestration.
- `.sh` files are retained as compatibility entrypoints and mostly forward to Python.
- `gh-address-cr/scripts/cli.py` is the unified Python dispatcher for the main command set.
- Tests are organized around Python behavior first, then shell wrapper syntax compatibility.

- `github_thread` items are synced from GraphQL thread snapshots.
- `local_finding` items are ingested from a local review adapter.
- local findings can now be explicitly closed in-session with `session_engine.py close-item`.
- `final_gate.sh` evaluates both:
  - session blocking item count
  - unresolved GitHub thread count

The session state is stored in a PR-scoped workspace under the user cache directory:

- workspace: `<owner>__<repo>/pr-<pr>/`
- session: `session.json`
- GitHub snapshots: `threads.jsonl`
- handled threads: `handled_threads.txt`
- audit log: `audit.jsonl`
- audit summary: `audit_summary.md`
- findings: `findings-*.json` and `code-review-findings.json`
- replies: `reply-*.md`
- loop requests: `loop-request-*.json`
- validation records: `validation-*.json`

The session also tracks loop-safety metadata per item:

- `repeat_count`: how many times the same local finding was re-ingested
- `reopen_count`: how many times a previously closed/deferred/clarified item was reopened
- claim lease fields so stale ownership can be reclaimed

## Local AI Review Ingestion

Use `scripts/run_local_review.sh` to feed local AI findings into the PR session:

```bash
scripts/run_local_review.sh --source local-agent:codex owner/repo 123 ./adapter.sh --base main --head HEAD
```

Adapter contract:

- adapter prints a JSON array to stdout
- each finding should include `title`, `body`, `path`, `line`
- optional fields: `severity`, `category`, `confidence`

This path does not auto-post to GitHub. It creates local session items that can be fixed and verified in the same workflow as remote review threads.

If the producer is a local `code-review` run, use the built-in adapter backend:

```bash
python3 gh-address-cr/scripts/cli.py prepare-code-review mixed owner/repo 123
cat findings.json | python3 gh-address-cr/scripts/cli.py review owner/repo 123 --input -
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

If your review tool already produces findings JSON, you do not need a custom adapter command. Use `scripts/ingest_findings.sh` instead:

```bash
cat findings.json | scripts/ingest_findings.sh --source local-agent:code-review owner/repo 123
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
scripts/publish_finding.sh --repo owner/repo --pr 123 local-finding:<fingerprint>
```

To reclaim expired item claims inside a PR session:

```bash
python3 gh-address-cr/scripts/session_engine.py reclaim-stale-claims owner/repo 123
```

To apply a terminal local finding resolution atomically, use:

```bash
python3 gh-address-cr/scripts/session_engine.py resolve-local-item owner/repo 123 local-finding:<fingerprint> fix --note "Fixed locally and verified."
python3 gh-address-cr/scripts/session_engine.py resolve-local-item owner/repo 123 local-finding:<fingerprint> clarify --note "Expected behavior."
python3 gh-address-cr/scripts/session_engine.py resolve-local-item owner/repo 123 local-finding:<fingerprint> defer --note "Deferred to a follow-up PR."
```

## Python-First Script Layout

The main logic now lives in Python under `gh-address-cr/scripts/`:

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

The matching `.sh` files are kept for backward compatibility with existing skill prompts and operator habits.

Unified CLI examples:

```bash
python3 gh-address-cr/scripts/cli.py run-once owner/repo 123
python3 gh-address-cr/scripts/cli.py final-gate --no-auto-clean owner/repo 123
python3 gh-address-cr/scripts/cli.py session-engine gate owner/repo 123
python3 gh-address-cr/scripts/cli.py ingest-findings --source local-agent:code-review owner/repo 123 --input findings.json
python3 gh-address-cr/scripts/cli.py review owner/repo 123 --input -
python3 gh-address-cr/scripts/cli.py findings owner/repo 123 --input -
python3 gh-address-cr/scripts/cli.py session-engine resolve-local-item owner/repo 123 local-finding:<fingerprint> fix --note "Fixed locally."
```

## Testing

Run the current automated checks with:

```bash
python3 -m unittest discover -s tests
bash -n gh-address-cr/scripts/*.sh
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
npx skills add https://github.com/RbBtSn0w/gh-address-cr-skill --skill gh-address-cr
```

## Breaking changes (2026-04-09)

- `scripts/batch_resolve.sh` now requires an approved list format:
  - one thread per line: `APPROVED <thread_id>`
  - empty lines and `#` comments are allowed
  - raw thread-id lines now fail fast
- `scripts/list_threads.sh` now uses the latest thread comment as primary context and emits:
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
- Mandatory final gate (`final_gate.sh`) before completion
- Session-scoped state tracking to avoid duplicate work
- Audit log + audit summary + summary hash output
- Python-first implementation with shell compatibility wrappers
- Module-split automated tests for session, wrappers, and helper scripts

## Skill folder

- `gh-address-cr/`
  - `SKILL.md`
  - `agents/openai.yaml`
  - `scripts/*.py`
  - `scripts/*.sh` (compat wrappers)
  - `assets/reply-templates/*`
  - `references/cr-triage-checklist.md`

## Quick usage after installation

```bash
scripts/run_once.sh --audit-id run-YYYYMMDD owner/repo 123
scripts/run_local_review.sh --source local-agent:codex owner/repo 123 ./adapter.sh
scripts/post_reply.sh --repo owner/repo --pr 123 --audit-id run-YYYYMMDD <thread_id> "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md"
scripts/resolve_thread.sh --repo owner/repo --pr 123 --audit-id run-YYYYMMDD <thread_id>
scripts/final_gate.sh --auto-clean --audit-id run-YYYYMMDD owner/repo 123
```

## Operating Modes

This skill supports several distinct operating modes. The session model is the same in all of them, but the required commands differ.

### Mode 1: GitHub Thread Only

Use this when the PR already has remote review threads and there is no local AI review input.

Example:

```bash
scripts/run_once.sh --audit-id run-20260412 owner/repo 123

# inspect one unresolved GitHub thread
scripts/generate_reply.sh --mode fix --severity P2 "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md" abc123 "src/app.py" "python3 -m unittest" "passed" "Added the missing guard."
scripts/post_reply.sh --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md"
scripts/resolve_thread.sh --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID

scripts/final_gate.sh --auto-clean --audit-id run-20260412 owner/repo 123
```

Rules:

- GitHub thread items require both `post_reply.sh` and `resolve_thread.sh`
- `final_gate.sh` must pass before completion

### Mode 2: GitHub Thread Clarify / Defer

Use this when the review comment is not accepted as a code change and you need to respond with rationale.

Clarify example:

```bash
scripts/generate_reply.sh --mode clarify "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md" "The current control flow is intentional because initialization must stay lazy."
scripts/post_reply.sh --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md"
scripts/resolve_thread.sh --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID
```

Defer example:

```bash
scripts/generate_reply.sh --mode defer "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md" "This requires broader refactoring and is deferred to a follow-up PR."
scripts/post_reply.sh --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md"
scripts/resolve_thread.sh --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID
```

Rules:

- even without code changes, GitHub thread items still require reply plus resolve
- defer/clarify should carry rationale, not just a status change

### Mode 3: Local Finding Only

Use this when you want to run local AI review without waiting for GitHub or Copilot review comments.

Example:

```bash
scripts/run_local_review.sh --source local-agent:codex owner/repo 123 ./adapter.sh

python3 gh-address-cr/scripts/session_engine.py list-items owner/repo 123 --item-kind local_finding --status OPEN
python3 gh-address-cr/scripts/session_engine.py update-item owner/repo 123 local-finding:FINGERPRINT ACCEPTED --note "Confirmed locally."
python3 gh-address-cr/scripts/session_engine.py update-item owner/repo 123 local-finding:FINGERPRINT FIXED --note "Implemented fix."
python3 gh-address-cr/scripts/session_engine.py update-item owner/repo 123 local-finding:FINGERPRINT VERIFIED --note "Validated with targeted tests."
python3 gh-address-cr/scripts/session_engine.py close-item owner/repo 123 local-finding:FINGERPRINT --note "Closed after local validation."

scripts/final_gate.sh --no-auto-clean --audit-id run-20260412 owner/repo 123
```

Rules:

- local findings do not require GitHub reply/resolve unless you choose to publish them
- they still participate in the same session gate
- terminal local-item transitions require `--note`

### Mode 4: Mixed Session

Use this when the PR has both remote GitHub threads and local AI findings.

Example:

```bash
scripts/run_once.sh --audit-id run-20260412 owner/repo 123
scripts/run_local_review.sh --source local-agent:codex owner/repo 123 ./adapter.sh

# process GitHub items with reply + resolve
# process local items through session_engine.py transitions

scripts/final_gate.sh --no-auto-clean --audit-id run-20260412 owner/repo 123
```

Rules:

- GitHub items need reply plus resolve
- local items need valid state transitions and notes
- the PR is not clear until both session blocking count and unresolved GitHub thread count are zero

### Mode 5: Publish Local Finding Back To GitHub

Use this when a locally discovered issue should become visible in the GitHub PR discussion.

Example:

```bash
scripts/run_local_review.sh --source local-agent:codex owner/repo 123 ./adapter.sh
python3 gh-address-cr/scripts/session_engine.py list-items owner/repo 123 --item-kind local_finding --status OPEN

scripts/publish_finding.sh --repo owner/repo --pr 123 local-finding:FINGERPRINT
scripts/run_once.sh --audit-id run-20260412 owner/repo 123
```

What happens:

- the local finding is published as a GitHub review comment
- later GitHub sync can associate the local finding with the resulting thread
- from that point onward, the issue can be handled like a normal GitHub review item

### Mode 6: Direct Session Engine / Unified CLI

Use this when you need low-level session control or when integrating the skill into other automation.

Examples:

```bash
python3 gh-address-cr/scripts/cli.py run-once owner/repo 123
python3 gh-address-cr/scripts/cli.py final-gate --no-auto-clean owner/repo 123
python3 gh-address-cr/scripts/cli.py session-engine list-items owner/repo 123 --item-kind local_finding
python3 gh-address-cr/scripts/cli.py session-engine reclaim-stale-claims owner/repo 123
```

Rules:

- `cli.py` is the preferred Python entrypoint for automation
- `.sh` commands remain the stable compatibility surface for skill users

## Troubleshooting final gate failure

If `scripts/final_gate.sh` fails:

1. Read the pending table in terminal output and the printed audit summary path.
2. For each pending thread, verify both operations were completed: `scripts/post_reply.sh` and `scripts/resolve_thread.sh`.
3. Re-run `scripts/run_once.sh --show-all ...` to compare unresolved vs handled state.
4. Resolve remaining threads, then re-run `scripts/final_gate.sh`.

## CI semantic release (tag + changelog)

This repo includes a `semantic-release` workflow:

- Trigger: push to `main`
- Input: Conventional Commits history
- Output: semantic version tag (`vX.Y.Z`) + GitHub Release + `CHANGELOG.md`

Commit format examples:

```text
feat: add strict unresolved-thread guard in final gate
fix: avoid duplicate handled-state writes when thread already resolved
docs: clarify npx skills update behavior
```
