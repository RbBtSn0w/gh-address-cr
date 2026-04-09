---
name: gh-address-cr
description: Use when resolving GitHub PR review threads that require evidence-first replies, explicit resolve actions, and a mandatory final unresolved-thread gate before completion.
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
3. For each thread: `understand -> analyze/decide (Accept/Defer/Clarify) -> act (fix code OR write rationale) -> evidence reply -> resolve`. (Note: You MUST resolve the thread on GitHub after replying to pass the final gate).
   - `post_reply` and `resolve_thread` are separate atomic operations. Both MUST be executed for handled threads.
4. Use minimal fixes and targeted tests first.
5. Before completion message, run hard gate (MANDATORY):
   - `scripts/final_gate.sh [--auto-clean|--no-auto-clean] [--audit-id <id>] <owner/repo> <pr_number>`
6. Only if gate passes, send merge-readiness summary.

## Decision Matrix (Analysis Phase)

Before modifying code, you MUST analyze the necessity of the CR suggestion:
- **Accept (Bug/Logic Error):** If the suggestion identifies a real issue or valid improvement with low architectural cost -> Proceed to fix code and generate evidence.
- **Defer (Nit/Preference with high cost):** If it's a stylistic preference requiring massive refactoring or architectural decay -> Do not change code. Use `scripts/generate_reply.sh --mode defer` to generate the trade-off explanation.
- **Clarify (Question/Misunderstanding):** If the reviewer misunderstood the logic or asks a question -> Do not change code. Use `scripts/generate_reply.sh --mode clarify` to generate the technical rationale.

## Hard Constraints (No Bypass)

- Never declare "done" without `final_gate.sh` pass.
- Never bypass state tracking with ad-hoc batch scripts. Only use `scripts/batch_resolve.sh` with an approved list produced after per-thread analysis and evidence drafting.
- If unresolved exists, keep iterating; do not send completion summary.
- Each mid-run update must include either a pending list or explicit `Verified: 0 Unresolved Threads found`.

## Completion Output Contract

Any final completion message must include:

1. `final_gate` command used
2. gate result line: `Verified: 0 Unresolved Threads found`
3. unresolved count = 0 confirmation
4. audit summary path + sha256

## Mandatory Evidence & Rationale

- **If Accepted (Code Changed):** Provide Commit `<hash>`, Files `<file1,file2>`, and Validation `<test command>` + `<result>`. Never resolve an accepted thread without these 3 items.
- **If Deferred/Clarified (No Code Changed):** Provide a detailed, professional Rationale explaining why the code remains as is (e.g., architectural constraints, pointing out misunderstood logic).

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
- Batch resolve from approved file: `scripts/batch_resolve.sh [--dry-run] [--yes] [--repo <owner/repo> --pr <number>] [--audit-id <id>] <approved_threads_file>` (format: `APPROVED <thread_id>`)
- Generate reply draft: `scripts/generate_reply.sh [--mode fix|clarify|defer] [--severity P1|P2|P3] <output_md> [args...]`
- Clean local cache: `scripts/clean_state.sh [--repo <owner/repo> --pr <number> | --all] [--clean-tmp]`
- Audit report: `scripts/audit_report.sh <owner/repo> <pr_number>`
- Templates: `assets/reply-templates/`
- Reference checklist: `references/cr-triage-checklist.md`

## Troubleshooting `final_gate` Failure

If `scripts/final_gate.sh` fails:

1. Read the pending table in terminal output and the audit summary file path printed by `final_gate.sh`.
2. For each pending `thread_id`, verify if reply and resolve were both completed (reply-only is insufficient).
3. Re-run `scripts/run_once.sh --show-all ...` to compare unresolved and handled state.
4. Post missing evidence reply and resolve missing threads.
5. Re-run `scripts/final_gate.sh ...` and only declare completion after `Verified: 0 Unresolved Threads found`.

## Fast Path

1. `scripts/run_once.sh --audit-id run-20260324 github/spec-kit 1906` to get unresolved threads excluding already-handled IDs.
2. **Analyze**: Decide whether to Accept, Defer, or Clarify.
3. Generate reply draft:
   - If Accepted (Code changed): `scripts/generate_reply.sh --mode fix --severity P2 /tmp/reply.md <commit> "<file1,file2>" "<test_cmd>" "<result>" "<why>"`
   - If Clarified (No code changed): `scripts/generate_reply.sh --mode clarify /tmp/reply.md "<detailed rationale why current logic is correct>"`
   - If Deferred (No code changed): `scripts/generate_reply.sh --mode defer /tmp/reply.md "<detailed rationale why this is deferred>"`
4. Preview:
   - `scripts/post_reply.sh --dry-run <thread_id> /tmp/reply.md`
5. Execute:
   - `scripts/post_reply.sh --repo github/spec-kit --pr 1906 --audit-id run-20260324 <thread_id> /tmp/reply.md`
   - `scripts/resolve_thread.sh --repo github/spec-kit --pr 1906 --audit-id run-20260324 <thread_id>`
6. Hard gate before completion:
   - `scripts/final_gate.sh --auto-clean --audit-id run-20260324 github/spec-kit 1906`

State cache lives in a user cache directory by default (override with `GH_ADDRESS_CR_STATE_DIR`) to avoid repeated labor across rounds. If the cache is purged, the workflow can be rebuilt from GitHub thread state; the main downside is potential repeated work.
