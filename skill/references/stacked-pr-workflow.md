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

Stack merge operations remain GitHub-owned. Merging a selected member includes
all lower unmerged members in one atomic contiguous operation; if one member is
blocked, none of that group merges. Use `gh stack sync` for routine
synchronization and `gh stack rebase` only when an explicit cascading rebase is
needed. After either operation, refresh every affected member, discard stale
ActionRequests and validation evidence, and repeat the corresponding PR-scoped
CR flow. Once the complete stack is merged, submit new work as a new stack
rooted at the trunk rather than extending the merged stack.

## Review Worker Boundary

The `gh-address-cr` worker may classify the item, edit and validate code in an
already-correct owning-layer checkout, submit evidence, and let the runtime
publish reply/resolve side effects. It must not change stack topology or run
checkout, cascading rebase, push, modify, unstack, queue, or merge operations
from an ActionRequest.

If the active checkout does not match the owning branch, stop the worker action
and request a separately authorized stack-management workflow. Do not silently
stash user work, switch branches, or force-update remote branches.

## Authorized Stack-Management Handoff

When the user has explicitly authorized fixing the lower member and updating
the stack, the separate stack-management workflow may:

1. Require a clean, recoverable working state.
2. Check out the owning branch with GitHub's stack tooling.
3. Apply, validate, and commit the lower-layer fix there.
4. Cascade the change through affected upper members.
5. Push the affected stack branches using the stack tool's safety rules.
6. Return to the intended development member.

These operations are not emitted or executed by `gh-address-cr`; GitHub's
`gh stack` workflow owns them. A coding agent may perform them only under that
separate authorization.

## Refresh After Propagation

A cascading rebase or push changes member revisions and may change the topology
fingerprint. After propagation:

1. Discard the old ActionRequest and response skeleton.
2. Rerun `address` or the runtime-provided refresh command for the owning PR.
3. Request fresh work and record validation against the current owning revision.
4. Revalidate every affected upper member whose revision changed.
5. Run the owning layer's `final-gate`, then run `final-gate --stack` through
   the selected upper member when aggregate readiness is required.

Durable GitHub reply/resolve facts may remain valid when their thread identity
survives. Validation and completion evidence never remain valid solely because
the thread identity is unchanged.
