# RFC 040: Stacked PR GA Alignment

Status: R1, R2 and R4 implemented and verified live in this change; V1 and V2 done; R3 needs no change. Static design reference: it records the decision and its evidence and does not select active work.
Trigger: GitHub stacked pull requests became generally available on 2026-10-06
(public preview since 2026-07-30). RFC 031 (`docs/rfcs/031-stacked-pr-support/`) was written against the preview.
Verification method: official GA docs and changelog, live GraphQL schema
introspection, code reading, and one real sandbox run on 2026-10-08 using
`scripts/e2e_stacked_pr_sandbox.py` plus `gh stack` v0.2.0 against
`RbBtSn0w/f2g-demo-portal-b-20260528` (fixture since cleaned).

Sources:
- <https://github.blog/changelog/2026-10-06-stacked-pull-requests-generally-available/>
- <https://docs.github.com/en/pull-requests/get-started/about-stacked-prs>
- <https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-stacked-pull-requests>
- <https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-stacked-pull-requests>

## 1. Verified findings

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| G1 | A rebase of a stack invalidates the revision binding of every member, including members whose own code did not change. | **Confirmed (code path with live data)** | Sandbox stack 9: after `gh stack rebase` + `gh stack push`, all three head OIDs changed while the upper two diffs were byte-identical. `compare_revision_binding` with the pre-rebase heads against the live context returned `STALE_REQUEST_CONTEXT` for PR 6, 7 and 8. Not run end to end with a `fix` decision (see G8). |
| G2 | The topology fingerprint couples a member's evidence to every other member, including members above it. | **Confirmed (code reading)** | `_fingerprint_present` hashes `member.to_dict()` for all members, including each `head_oid`. A push to the top layer therefore stales evidence of the bottom layer, although a lower layer never depends on a higher one. Not exercised live. |
| G3 | Review threads survive a stack rebase without our help. | **Confirmed (live)** | After inserting a line above the reviewed line in the bottom layer: GitHub relocated the thread from line 1 to line 2 (`line=2, originalLine=1`), `isOutdated=false`, still resolved. Upper-layer threads kept their lines, `originalCommit` stayed the old OID, `commit` moved to the new head. The existing `is_stale_or_outdated_github_thread` check is sufficient; no thread-relocation logic is needed. |
| G4 | After a rebase with unrelated content changes, `final-gate` and `final-gate --stack` still pass for items that need no validation evidence. | **Confirmed (live), narrow** | All three layers and `--stack` returned PASSED. The fixture items were `reject` decisions with no validation evidence, so the binding path was not reached. The `fix`-evidence path is covered end to end by R4 (`fix-evidence` scenario). |
| G5 | "Public preview" wording is stale. | **Confirmed** | `README.md` (stacked-PR section), `skill/references/status-action-map.md`, docstrings in `github/client.py` (`get_stack_context`) and `runtime_kernel/stack.py` (`unavailable_stack_context`), and `docs/rfcs/031-stacked-pr-support/research.md` (left as the historical record). GHES is not covered until an upcoming release, so the `unavailable` fail-open path stays valid and must be reworded, not removed. |
| G6 | The GraphQL surface used by `get_stack_context` is unchanged at GA. | **Confirmed (live)** | Introspection: `PullRequestStack{baseRefName,entries,id,number,size}`, `PullRequestStackEntry{id,position,pullRequest,stack}`, `PullRequest.{stack,stackEntry,mergeQueueEntry}`; no stack mutation exists. The 3-member read worked unchanged. |
| G7 | Merging the bottom PR may leave a single-member remainder that our invariants classify as `invalid`. | **Refuted (live, V1)** | Stack 13 (PR 10/11/12), squash merges via `gh stack merge`. Merged PRs stay in `entries` at their original positions with `state=MERGED`; `size` stays 3 and positions are not renumbered. After merging 10 and 11 the single open member (12) projected `present`, valid. The existing merged-prefix invariant matches GA. The docs' "moves to the bottom" refers to base retargeting (`base_ref_name` becomes `main`), not to entry positions. |
| G11 | GitHub rewrites the heads and bases of the remaining members when a lower member merges, and the content (tree) does not change. | **Confirmed (live, V1)** | Merging PR 10: PR 11 head 9330a32 -> 2069534, base -> `main`; PR 12 head 298656e -> 2d4a1a0. Merging PR 11: PR 12 head -> 49d59cc. Tree OIDs stayed 8236e4d (PR 11) and a665a90 (PR 12) across every rewrite. Under `revision_binding.v1` this would have staled the evidence of every remaining member after every lower merge; under v2 it stays current. Condition: the trunk had no unrelated changes in between (squash merge of the lower layer). |
| G8 | Branching stacks (a stack based on another stack) and base-branch retargeting may trip `lowest_unmerged_base_mismatch` / `dependency_chain_mismatch` transiently. | **Refuted (live, V2)** | Stack 17 (PR 14-16) and a branching stack 20 (PR 18, 19) created with `gh stack init --base <top of stack 17>`. Stack 20 reported `stack.baseRefName` = the stack-17 top branch and projected `present`. After merging stack 17 (all members MERGED, still `present`) and deleting its top branch, GitHub retargeted PR 18 to `main` and changed `stack.baseRefName` to `main` in the same observation; three polls over ~24 s were `present` with `size=2`, heads and trees unchanged (no rebase on retarget). Single-query consistency of the two fields was never violated in this run; a sub-second race between them cannot be excluded. |
| G12 | A merged member's head tree is unreadable once its branch is deleted. | **Confirmed (live, V2)** | After the stack-17 top branch was deleted, PR 16 (MERGED) had no `headRef`; the client yielded no tree and the context stayed `present` only because MERGED members may omit the tree (R2). Without that leniency every stack containing a merged member with a deleted branch would be `invalid`. |
| G9 | Merge queue treats a stack as one merge group; ejecting one PR ejects everything above it. | **Docs only** | We block on any non-empty `merge_queue_state` (`STACK_MEMBER_QUEUED`), which is consistent but does not model the cascade. Low priority. |
| G10 | Auto-merge for stacks: sources disagree. | **Unresolved** | The merging page says "not supported"; the changelog says it is rolling out over the following weeks. We make no claim either way. |

## 2. Escape analysis

1. The sandbox harness has no rebase scenario and no `fix` decision: `exercise`
   runs a hard-coded `reject` sequence, so the evidence-binding path is never
   executed against a real stack change.
2. `scripts/e2e_stacked_pr_sandbox.py cleanup` verifies every PR head against the
   manifest. That guard is correct, but any legitimate rebase test requires
   hand-editing the manifest first.
3. RFC 031 validated against the preview schema only; nothing re-checks the
   assumption "stack identity and per-member head are stable between the
   `address` and `publish` steps" under GitHub-initiated rebases.

## 3. Requirements

### P0
- **R1 (G5)**: Replace "preview" wording with GA wording. State that stack context
  is `unavailable` on hosts without the feature (older GHES), and that this
  remains fail-open for single-layer operations and fail-fast for `--stack`.
  No behavior change.
  AC: grep for `public-preview` / `preview` in the stacked-PR docs and docstrings
  returns nothing stale; docs tests still pass.

- **R2 (G1, G2)**: Bind validation evidence and action requests to what was
  actually validated, the cumulative content of the member, instead of commit
  identity plus whole-stack topology.
  Proposal: `revision_binding.v2` gates on `pr_number` and `head_tree_oid` (the
  tree of the member's head commit, which already contains the trunk plus every
  lower layer). `head_oid`, `stack_number`, `stack_position` and
  `topology_fingerprint` stay in the record for audit and diagnostics but no longer
  gate. Consequences:
  - A GitHub-initiated or `gh stack`-initiated rebase that does not change
    cumulative content keeps evidence valid.
  - A change in a lower layer changes the upper layers' trees, so their evidence is
    stale (correct).
  - A change in an upper layer cannot stale a lower layer (fixes G2).
  - Position renumbering after a bottom merge no longer stales anything.
  AC: see tests T1-T5. Stale/current decision for the 2026-10-08 sandbox rebase:
  PR 6, 7, 8 all stale (content changed in the bottom layer); for a pure rebase
  with no content change: all current.
  Status: implemented in `runtime_kernel/stack.py` (`head_tree_oid` fact,
  `revision_binding.v2`, `compare_revision_binding`) and `github/client.py`
  (stack query reads `headRef.target { oid tree { oid } }`; the tree counts only
  when read from the same commit as `headRefOid`). A MERGED member may omit the
  tree because its head branch is usually deleted; it never gates evidence.
  Tests: `StackRevisionBindingContentTests` (7), two client tests, existing
  stale-simulation tests moved from `head_oid` to `head_tree_oid`.

### P1
- **R3 (G7, G8)**: No invariant change. V1 (merged prefix, one open member) and V2
  (branching stack, base deletion and retarget) both matched the existing
  invariants. Closed as "verified, no change needed".
- **R4 (harness)**: `scripts/e2e_stacked_pr_sandbox.py` gains `refresh`, `rebase`
  and `merge-bottom`, and `cleanup` tolerates the state they produce.
  Status: implemented and run live on 2026-10-08 (stack 24: provision, rebase,
  verify, merge-bottom, verify, cleanup, no manual manifest edit).
  - `refresh` proves fixture ownership by title, body and head branch (not head
    revision), then records head/base drift; a base outside the fixture chain or the
    trunk still fails fast.
  - A layer base may be the trunk, because GitHub retargets remaining members when a
    lower one merges.
  - `cleanup` skips closing merged PRs, tolerates an already-deleted branch, and
    tolerates a stack with nothing left to unstack.
  - `fix-evidence` resolves the middle thread as a `fix` with validation evidence and
    `gate` reports each layer's own verdict. Live 2026-10-08, same evidence, two
    paths: (A) `rebase` that edits the bottom layer -> middle layer
    `FINAL_GATE_STALE_REVISION_EVIDENCE` (stack 36); (B) `merge-bottom`, where GitHub
    rebased the remaining members (middle head 104bb28 -> eeb64b7, content
    unchanged) -> middle layer still `PASSED` (stack 40). This is the end-to-end proof
    of R2; under `revision_binding.v1` path B would have gone stale.
  - Limitation: merged fixture files stay on the sandbox `main`.

### P2
- **R5 (G9)**: Model queue-group ejection only if a real user-visible failure shows
  up. Not scheduled.

### Out of scope
- Consuming the `stacked` webhook action or the REST stack endpoints (the runtime
  has no listener; GraphQL read remains sufficient).
- Wrapping any `gh stack` command (RFC 031 Decision 1 stands).
- Auto-merge claims (G10).

## 4. Architecture Preflight (blast-radius trigger: artifact-backed decision surface, session persistence semantics, `final-gate` truth)

| Item | Answer |
|---|---|
| Authoritative state owner | Unchanged. Per-PR session owns items and evidence; GitHub owns stack topology and commit/tree identity. The binding is a recorded fact about what was validated, never the truth about the stack. |
| External facts / event inputs | GraphQL per member: `headRefOid` (existing) plus `commit.tree.oid` of the head (new field on the existing stack query; no extra request). Everything else as in RFC 031. |
| Projection shape | `PullRequestMemberFact` gains `head_tree_oid`. `revision_binding.v2` = `{schema_version, pr_number, head_tree_oid}` as the gating subset plus the existing audit fields. `StackContext.to_dict()` exposes `head_tree_oid` per member. |
| Decision function | `compare_revision_binding`: returns `None` iff `pr_number` and `head_tree_oid` match; otherwise `STALE_REQUEST_CONTEXT`. Availability handling (`invalid` / `unavailable` / `absent`) is unchanged. One function, fewer comparison fields than today. |
| Side-effect plan | None. No GitHub or session writes added. |
| Artifact truth / self-reference | Bindings are read back only to be compared with a fresh GitHub observation. No report or summary is trusted as truth. Unchanged. |
| Compatibility | `revision_binding.v1` records lack `head_tree_oid`: they compare as `FINAL_GATE_UNBOUND_REVISION_EVIDENCE` / stale and require fresh evidence. Fail-fast, no shim, versioned in `skill/references/agent-protocol.md`. Stacked evidence was introduced in 3.x and is short-lived, so the cost is one re-validation. |
| Recovery / replay | Re-run `address` for the owning PR; the new request carries a v2 binding. |
| Executable contract tests | See section 5. |
| Branch-growth check | R2 reduces the number of comparison fields and removes the cross-member coupling; it adds no new state flag. |

## 5. Test plan (RED first)

- T1 `compare_revision_binding`: same tree, different `head_oid` and different
  `topology_fingerprint` -> current.
- T2 same `head_oid`, different tree (cannot happen in git, guards the field choice)
  -> stale.
- T3 upper-layer tree changes, lower layer binding -> current; reverse -> stale.
- T4 `revision_binding.v1` record -> stale / unbound (fail-fast).
- T5 position renumbering with equal tree -> current.
- T6 contract test for `agent-protocol.md` binding schema version.
- Harness: R4 scenario reproduces the 2026-10-08 sandbox run with a `fix` decision
  and asserts stale before R2, current after R2 for a pure rebase.

## 6. Verification still required before implementation

- **V1 (done 2026-10-08, G7 and tree stability)**: results are recorded in G7 and
  G11. Not covered: a `fix` item with real validation evidence carried across the
  merge (the binding comparison itself is covered by unit tests with the observed
  head/tree behavior), a trunk that moved with unrelated files (tree changes, so
  evidence goes stale, conservative by design), and a repository with
  delete-branch-on-merge enabled (merged heads unreadable; covered only by the unit
  test for a MERGED member without a tree).
- **V2 (done 2026-10-08, G8 and G12)**: results are recorded in G8 and G12. Not
  covered: a head rewrite by GitHub on retarget with a squash-merged base (none
  occurred here) and a sub-second race between PR base and stack base.
- **V3 (done 2026-10-08)**: `Commit.tree.oid` is selectable through GraphQL
  (checked via `pullRequest.commits(last:1){nodes{commit{oid tree{oid}}}}`). The
  member's tree must be read for the same commit as `headRefOid`; use
  `headRef { target { ... on Commit { oid tree { oid } } } }` in the stack query and
  reject the observation as invalid when its `oid` differs from `headRefOid`.

## 7. Open decisions (maintainer)

1. **Binding key** (recommend `head_tree_oid`; implemented on that basis).
   - Option A, recommended: `head_tree_oid`. API-only, one extra field, exact
     "validated content unchanged" semantics. Conservative when the trunk moved
     with unrelated files.
   - Option B: per-layer diff fingerprint (`pulls/{n}/files`). Survives trunk
     movement, but is paginated, heavier, and a layer diff is not sufficient when a
     lower layer changed.
   - Option C: keep `head_oid` + topology and document the cost. Zero work, keeps
     the over-invalidation of G1/G2.
2. **Order**: R1 ships on its own as a docs-only PR; R2/R3 follow V1. Dependent
   PRs follow `pr-stacking-strategy`; R1 is independent of R2.
