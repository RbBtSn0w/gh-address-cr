---
name: gh-address-cr
description: Resolve GitHub PR review comments end-to-end with evidence. Use when asked to process CR comments one by one, verify fixes, reply per thread, fix unresolved issues, produce minimal repair plans, explain why new CRs appear later, and decide whether each CR must be fixed before merge.
---

# gh-address-cr

Use this skill in strict incremental mode to minimize token usage while keeping review quality.

## Non-Negotiable Rule

`final_gate.sh` pass is mandatory before any completion statement.

- Never output "done", "all resolved", "completed", or equivalent unless:
  - `scripts/final_gate.sh <owner/repo> <pr_number>` has just passed, and
  - output includes `Verified: 0 Unresolved Threads found`.
- If gate fails, continue iteration; completion summary is forbidden.

## Core Protocol (Token-Optimized)

1. Run incremental triage first:
   - `scripts/run_once.sh [--audit-id <id>] <owner/repo> <pr_number>`
2. Process only unresolved + unhandled threads.
3. For each thread: `understand -> verify -> act -> evidence reply -> resolve/keep-open`.
4. Use minimal fixes and targeted tests first.
5. Before completion message, run hard gate (MANDATORY):
   - `scripts/final_gate.sh [--auto-clean|--no-auto-clean] [--audit-id <id>] <owner/repo> <pr_number>`
6. Only if gate passes, send merge-readiness summary.

## Hard Constraints (No Bypass)

- Never declare "done" without `final_gate.sh` pass.
- Never bypass state tracking with ad-hoc batch scripts.
- If unresolved exists, keep iterating; do not send completion summary.
- Each mid-run update must include either a pending list or explicit `Verified: 0 Unresolved Threads found`.

## Completion Output Contract

Any final completion message must include:

1. `final_gate` command used
2. gate result line: `Verified: 0 Unresolved Threads found`
3. unresolved count = 0 confirmation
4. audit summary path + sha256

## Mandatory Evidence (Short Form)

- Commit: `<hash>`
- Files: `<file1,file2>`
- Validation: `<test command>` + `<result>`
- Never resolve a thread without these 3 items.

## Must-Fix Rule

- Default must-fix: correctness bugs, data loss risks, platform/runtime breakage, packaging/install breakage, P1/P2 regressions.
- Can defer with rationale: style-only, naming preference, non-blocking wording improvements.

## Why CR Appears Later (Use This Exact Logic)

- GitHub review bots run asynchronously.
- New commits trigger re-analysis and can generate new comments.
- Old threads can become outdated; new ones may appear on different lines.

## Reusable Resources

- One-shot triage + state snapshot: `scripts/run_once.sh [--show-all] [--audit-id <id>] <owner/repo> <pr_number>`
- Final completion gate (mandatory): `scripts/final_gate.sh [--auto-clean|--no-auto-clean] [--audit-id <id>] <owner/repo> <pr_number>`
- Post reply: `scripts/post_reply.sh [--dry-run] [--repo <owner/repo> --pr <number>] [--audit-id <id>] <thread_id> <reply_file>`
- Resolve thread: `scripts/resolve_thread.sh [--dry-run] [--repo <owner/repo> --pr <number>] [--audit-id <id>] <thread_id>`
- Mark handled without resolving: `scripts/mark_handled.sh [--repo <owner/repo> --pr <number>] <thread_id>`
- Batch resolve from file: `scripts/batch_resolve.sh [--dry-run] [--yes] [--repo <owner/repo> --pr <number>] [--audit-id <id>] <thread_ids_file>`
- Generate fixed-reply draft: `scripts/reply_fixed.sh [--severity P1|P2|P3] <output_md> <commit_hash> <files_csv> <test_command> <test_result> [why]`
- Clean local cache: `scripts/clean_state.sh [--repo <owner/repo> --pr <number> | --all] [--clean-tmp]`
- Audit report: `scripts/audit_report.sh <owner/repo> <pr_number>`
- Templates: `assets/reply-templates/`
- Reference checklist: `references/cr-triage-checklist.md`

## Fast Path

1. `scripts/run_once.sh --audit-id run-20260324 github/spec-kit 1906` to get unresolved threads excluding already-handled IDs.
2. Generate reply draft:
   - `scripts/reply_fixed.sh --severity P2 /tmp/reply.md <commit> "<file1,file2>" "<test_cmd>" "<result>" "<why>"`
3. Preview:
   - `scripts/post_reply.sh --dry-run <thread_id> /tmp/reply.md`
4. Execute:
   - `scripts/post_reply.sh --repo github/spec-kit --pr 1906 --audit-id run-20260324 <thread_id> /tmp/reply.md`
   - `scripts/resolve_thread.sh --repo github/spec-kit --pr 1906 --audit-id run-20260324 <thread_id>`
5. Hard gate before completion:
   - `scripts/final_gate.sh --auto-clean --audit-id run-20260324 github/spec-kit 1906`

State cache lives in a user cache directory by default (override with `GH_ADDRESS_CR_STATE_DIR`) to avoid repeated labor across rounds. If the cache is purged, the workflow can be rebuilt from GitHub thread state; the main downside is potential repeated work.
