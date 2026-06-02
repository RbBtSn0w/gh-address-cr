# Workflows

## Core Workflow

```text
       [ Start PR Review Session ]
                   |
                   v
+-------------------------------------+      (Fetch PR threads, sync session)
|          1. gh-address-cr address/review       | <-----------------------------------------+
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
| 4a. agent       | | 4b. agent       |     | 4c. agent       |                   |
|     submit/fix  | |     submit     |     |     submit      |                   |
|     evidence    | |     clarify    |     |     defer       |                   |
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
gh-address-cr agent publish owner/repo 123
```

Defer example:

```bash
gh-address-cr submit-action <action-request.json> --resolution defer --note "Deferred to a follow-up PR." --reply-markdown "This requires broader refactoring and is deferred to a follow-up PR."
gh-address-cr agent publish owner/repo 123
```

Rules:

- even without code changes, GitHub thread items still require reply plus resolve
- defer/clarify should carry rationale, not just a status change
- low-level resolve paths are intentionally blocked until reply evidence exists in the session or the same action posts a fresh reply

### Mode 3: Local Finding Only

Use this when you want to run local AI review without waiting for GitHub or Copilot review comments.

Example:

```bash
gh-address-cr adapter owner/repo 123 ./adapter.sh

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
