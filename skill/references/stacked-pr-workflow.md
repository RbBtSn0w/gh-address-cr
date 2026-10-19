# Stacked PR Ownership and Handoff

Use this reference when review feedback targets one stack member while another
member is currently checked out.

## Ownership Rule

Every review item remains owned by exactly one pull request. For a stacked
request, read the owner from:

```text
ActionRequest.repository_context.stack_context.selected_pr.pr_number
ActionRequest.repository_context.stack_context.selected_pr.head_ref_name
```

The reported `head_ref_name` is the owning branch. Do not implement a
lower-layer fix on an upper branch and do not attach an upper-branch commit to
the lower pull request's review evidence. If the reviewer comment identifies a
different concern that truly belongs to another layer, classify the original
item as `clarify`, `defer`, or `reject` with rationale and create or ingest the
separate owning-layer item.

## Multiple PRs and CR Sessions

A stack is a set of independent PR-scoped CR sessions, with one PR-scoped
session per stack member, not one shared review session. For a stack with bottom
`PR #101`, middle `PR #102`, and top `PR #103`:

1. Refresh the selected PR and read `stack_context.selected_pr.pr_number` and
   `head_ref_name` to identify the owning layer.
2. Run `review` or `address` with that exact PR number. Each member keeps its
   own session, findings, leases, replies, validation evidence, and
   `final-gate` result:

   ```text
   gh-address-cr address owner/repo 101 --lean
   gh-address-cr address owner/repo 102 --lean
   gh-address-cr address owner/repo 103 --lean
   ```

3. Resolve a finding only in the owning session (`agent next`, `agent resolve`,
   `agent submit`, and `agent publish` all use the owning PR number). A finding
   discovered while checking `PR #103` but introduced by `PR #101` is handed
   back to `PR #101`; it is not fixed or evidenced on `PR #103`.
4. Run the owning layer's `final-gate` after its evidence is complete. A green
   layer gate covers only that PR. Use `final-gate --stack` on `PR #102` or
   `PR #103` only when the user explicitly requests aggregate readiness; it
   evaluates the contiguous bottom-up range and reports the covered PRs.

Stack merge operations remain GitHub-owned. A direct merge of a selected member
includes all lower unmerged members in one atomic contiguous operation; if one
member is blocked, none of that group merges. A merge-queue submission is not a
completed merge; observe the queue and final PR states before claiming success. Use `gh stack sync` for routine
synchronization and `gh stack rebase` only when an explicit cascading rebase is
needed. After either operation, refresh every affected member, discard stale
ActionRequests and validation evidence, and repeat the corresponding PR-scoped
CR flow. Once the complete stack is merged, submit new work as a new stack
rooted at the trunk rather than extending the merged stack.

## Review Worker Boundary

The `gh-address-cr` worker may classify the item, edit and validate code in an
already-correct owning-layer checkout, submit evidence, and let the runtime
publish reply/resolve side effects. It must not change stack topology or run
checkout, cascading rebase, stack-wide push, modify, unstack, queue, or merge operations
from an ActionRequest.

The selected PR's ordinary fix push remains authorized by address/review;
stack-wide propagation is a different operation. If the active checkout differs,
pause this worker and hand off to a separately authorized stack-management workflow.
Check the user's existing instructions before asking again; do not silently stash
user work or force-update remote branches. Missing propagation authority leaves
Stack readiness pending, not the selected PR's own fix permission revoked.

## Authorized Stack-Management Handoff

When the user has explicitly authorized fixing the lower member and updating
the stack, the separate stack-management workflow may:

1. Require a clean, recoverable working state.
2. Check out the owning branch with GitHub's stack tooling.
3. Apply, validate, and commit the lower-layer fix there.
4. Cascade the change through affected upper members.
5. Push the affected stack branches using the stack tool's safety rules.
6. Return current remote heads, bases and content trees, the propagation result
   for every affected member, and which content was actually validated. Confirm
   lower-head ancestry in each affected upper member and inspect cumulative
   content for repairs lost during conflict resolution before resuming workers.

These operations are not emitted or executed by `gh-address-cr`; GitHub's
`gh stack` workflow owns them. A coding agent may perform them only under that
separate authorization, including authorization already supplied in the user task.
Do not use manual parent merges as a workaround for missing authority or native
synchronization; an intentionally authorized alternative recovery must prove the
same postconditions.

## Refresh After Propagation

A cascading rebase or push changes member commit ids and may change the topology
fingerprint. Member content (`head_tree_oid`) is central to revision binding,
but the runtime also checks selected-PR identity, membership and context validity.
A head-SHA-only rewrite does not by itself invalidate content-bound evidence;
let the runtime determine which requests and evidence remain valid. After propagation:

1. Discard the old ActionRequest and response skeleton.
2. Rerun `address` or the runtime-provided refresh command for the owning PR.
3. Request fresh work and record validation against the current owning revision.
4. Revalidate every affected upper member whose content changed.
5. Run the owning layer's `final-gate`, then run `final-gate --stack` through
   the selected upper member when aggregate readiness is required.

Durable GitHub reply/resolve facts may remain valid when their thread identity
survives. Validation and completion evidence never remain valid solely because
the thread identity is unchanged.

## Completion boundary for multi-PR work

Record the owning repair head and affected upper members in the existing task
output. Until the management workflow returns verified remote propagation,
report the owning PR result separately from pending Stack readiness. Several
per-PR gates passing is not a substitute for that return check. Quiet monitoring
must not terminate as clean while known propagation or validation is pending.

If a lower PR merges or GitHub changes remaining heads/bases while work is active,
refresh remote state before further mutations. `gh stack view` alone may reflect
local tips; use current GitHub heads and fetched refs. Aggregate gate support
checks modeled PR/review/CI state; it does not prove that Git ancestry or intended
feature dependencies were established. Do not attribute such a check to the
runtime unless its machine contract actually reports it.

When the user requests overall Stack readiness or merge, run final-gate --stack
through the selected upper member, with --require-checks or the required-checks
mode appropriate to the task, after propagation is proven. Single-PR requests
remain single-PR scope and do not silently authorize merging or rewriting peers.

For FINAL_GATE_STALE_REVISION_EVIDENCE, compare old and current content trees and
follow the returned evidence recovery command. Changed content needs checks run
on that content or CI attached to that current head. Never bind an old-worktree
test to a new head merely by copying its SHA into agent evidence add. SHA-only
rewrites may retain content-bound evidence when the runtime confirms the tree is
unchanged. Do not reopen correctly resolved threads merely to retest code.
