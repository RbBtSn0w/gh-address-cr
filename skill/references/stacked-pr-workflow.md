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
