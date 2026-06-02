# Workflows

## Core Workflow

```text
       [ Start PR Review Session ]
                   |
                   v
+-------------------------------------+      (Fetch PR threads, exclude handled)
|          1. gh-address-cr run-once             | <-----------------------------------------+
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
|         5. gh-address-cr post-reply            |                                           |
+------------------+------------------+                                           |
                   |                                                              |
+------------------+------------------+      (MANDATORY for all paths)            |
|       6. gh-address-cr resolve-thread          |      (Local state marked 'Handled')       |
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
gh-address-cr run-once --audit-id run-YYYYMMDD owner/repo 123
gh-address-cr run-local-review --source local-agent:codex owner/repo 123 ./adapter.sh
gh-address-cr post-reply --repo owner/repo --pr 123 --audit-id run-YYYYMMDD <thread_id> "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md"
gh-address-cr resolve-thread --repo owner/repo --pr 123 --audit-id run-YYYYMMDD <thread_id>
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
gh-address-cr run-once --audit-id run-20260412 owner/repo 123

# inspect one unresolved GitHub thread
gh-address-cr generate-reply --mode fix --severity P2 "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md" abc123 "src/app.py" "python3 -m unittest" "passed" "Added the missing guard."
gh-address-cr post-reply --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md"
gh-address-cr resolve-thread --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID

gh-address-cr final-gate --auto-clean --audit-id run-20260412 owner/repo 123
```

Rules:

- GitHub thread items require both `gh-address-cr post-reply` and `gh-address-cr resolve-thread`
- `gh-address-cr resolve-thread` rejects silent resolve attempts when reply evidence is missing
- outdated / `STALE` GitHub threads still count as unresolved until explicitly handled
- `gh-address-cr final-gate` must pass before completion and now fails if a terminal GitHub thread has no reply evidence

### Mode 2: GitHub Thread Clarify / Defer

Use this when the review comment is not accepted as a code change and you need to respond with rationale.

Clarify example:

```bash
gh-address-cr generate-reply --mode clarify "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md" "The current control flow is intentional because initialization must stay lazy."
gh-address-cr post-reply --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md"
gh-address-cr resolve-thread --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID
```

Defer example:

```bash
gh-address-cr generate-reply --mode defer "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md" "This requires broader refactoring and is deferred to a follow-up PR."
gh-address-cr post-reply --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID "$GH_ADDRESS_CR_STATE_DIR/owner__repo/pr-123/reply.md"
gh-address-cr resolve-thread --repo owner/repo --pr 123 --audit-id run-20260412 THREAD_ID
```

Rules:

- even without code changes, GitHub thread items still require reply plus resolve
- defer/clarify should carry rationale, not just a status change
- low-level resolve paths are intentionally blocked until reply evidence exists in the session or the same action posts a fresh reply

### Mode 3: Local Finding Only

Use this when you want to run local AI review without waiting for GitHub or Copilot review comments.

Example:

```bash
gh-address-cr run-local-review --source local-agent:codex owner/repo 123 ./adapter.sh

gh-address-cr session-engine list-items owner/repo 123 --item-kind local_finding --status OPEN
gh-address-cr session-engine update-item owner/repo 123 local-finding:FINGERPRINT ACCEPTED --note "Confirmed locally."
gh-address-cr session-engine update-item owner/repo 123 local-finding:FINGERPRINT FIXED --note "Implemented fix."
gh-address-cr session-engine update-item owner/repo 123 local-finding:FINGERPRINT VERIFIED --note "Validated with targeted tests."
gh-address-cr session-engine close-item owner/repo 123 local-finding:FINGERPRINT --note "Closed after local validation."

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
gh-address-cr run-once --audit-id run-20260412 owner/repo 123
gh-address-cr run-local-review --source local-agent:codex owner/repo 123 ./adapter.sh

# process GitHub items with reply + resolve
# process local items through gh-address-cr session-engine transitions

gh-address-cr final-gate --no-auto-clean --audit-id run-20260412 owner/repo 123
```

Rules:

- GitHub items need reply plus resolve
- local items need valid state transitions and notes
- the PR is not clear until both session blocking count and unresolved GitHub thread count are zero

### Mode 5: Publish Local Finding Back To GitHub

Use this when a locally discovered issue should become visible in the GitHub PR discussion.

Example:

```bash
gh-address-cr run-local-review --source local-agent:codex owner/repo 123 ./adapter.sh
gh-address-cr session-engine list-items owner/repo 123 --item-kind local_finding --status OPEN

gh-address-cr publish-finding --repo owner/repo --pr 123 local-finding:FINGERPRINT
gh-address-cr run-once --audit-id run-20260412 owner/repo 123
```

What happens:

- the local finding is published as a GitHub review comment
- later GitHub sync can associate the local finding with the resulting thread
- from that point onward, the issue can be handled like a normal GitHub review item

### Mode 6: Direct Session Engine / Unified CLI

Use this when you need low-level session control or when integrating the skill into other automation.

Examples:

```bash
gh-address-cr run-once owner/repo 123
gh-address-cr final-gate --no-auto-clean owner/repo 123
gh-address-cr session-engine list-items owner/repo 123 --item-kind local_finding
gh-address-cr session-engine reclaim-stale-claims owner/repo 123
```

Rules:

- `gh-address-cr` is the preferred and stable automation entrypoint
- low-level resolve helpers are stricter than before: `resolve-thread` and batch resolve flows refuse resolve-only handling when reply evidence is absent
