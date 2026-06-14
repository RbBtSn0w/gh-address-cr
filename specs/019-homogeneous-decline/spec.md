# Spec: Homogeneous / Batch Decline Path for Reject & Clarify

- **Status**: Implemented
- **Origin**: [AI Feedback issue #135](https://github.com/RbBtSn0w/gh-address-cr/issues/135) — "No homogeneous/batch path for reject or clarify replies sharing one rationale"
- **Category**: workflow-gap
- **Skill version observed**: 3.0.0

## 1. Problem

`agent resolve` has a homogeneous/batch shortcut **only for the `fix` resolution**.
When a reviewer (or auto-reviewer) raises the *same* concern across many threads and
the agent wants to **decline** them all with one shared rationale (`reject` or
`clarify`), no symmetric shortcut exists. Each decline degrades to a per-thread
round-trip: `classify → request → fill reply_markdown → submit`.

Concrete report: PR #21 had 16 review threads; 8 were the identical auto-reviewer
nit ("wrap prose identifiers in backticks") declined with one identical rationale.
Declining scaled linearly with thread count because only `fix` supports homogeneous
resolution.

### Where the asymmetry lives (verified)

- `agent resolve` with no `<item_id>` routes to `workflow.fast_fix_matching_threads`
  (`commands/agent.py:486-511`), which **requires `--commit`** and hardcodes
  `classification="fix"` (`core/workflow.py:807`). `--homogeneous-reason` only
  attaches here.
- `--batch` (`agent_protocol.submit_batch_action_response`) is **fix-only**:
  `_batch_action_responses` raises `BATCH_UNSUPPORTED_RESOLUTION` when the resolution is
  not `fix` (`core/agent_protocol.py:746-748,771-776`), so `reject`/`clarify` cannot flow
  through the batch channel at all. Even within `fix`,
  `_validate_fix_all_input_item_reply_evidence` (`core/workflow.py:160-184`) requires each
  item to carry its own `summary` + `why`. There is therefore no batch path that lets a
  shared rationale decline many threads.
- For a thread decline, the action-response shape is `resolution` (`reject`/`clarify`)
  + `reply_markdown` + `note` — no commit/files/validation needed
  (`agent_protocol.py:604-616`).

## 2. Goals

1. A homogeneous decline path symmetric with the `fix` shortcut: one shared
   rationale resolves many matching threads in a single submission.
2. Reuse the existing safety gate — only collapse threads whose **first-body text is
   identical** (`_has_homogeneous_thread_bodies`), so distinct concerns are never
   silently declined with a generic reason.
3. Stable per-thread aliases in `--lean` output so long node-id suffixes
   (`…JX5-A` vs `…JX6qd`) no longer need to be hand-transcribed (secondary nit).

## 3. Non-goals

- No change to `defer` (out of scope; can follow the same template later).
- No change to the single-item decline flow.
- No auto-classification of *which* threads are homogeneous — the agent still
  supplies the file scope; the body-identity gate decides eligibility.

## 4. Proposed CLI surface

A resolution selector on the existing match-all path, mutually exclusive with `fix`:

```
gh-address-cr agent resolve <repo> <pr> \
  --reject  --homogeneous-reason "<why these are declined>" --match-files --files <paths>
gh-address-cr agent resolve <repo> <pr> \
  --clarify --homogeneous-reason "<reply markdown>"        --match-files --files <paths>
```

- `--reject` / `--clarify`: mutually exclusive; select the decline resolution.
- Reuses `--homogeneous-reason`, `--concern-label`, `--files`/`--file`, `--match-files`,
  `--include-stale`, `--publish`, `--agent-id`, `--now`.
- **Does not** require `--commit`, `--summary`, `--why`, `--validation`
  (decline carries no fix evidence).
- The shared `--homogeneous-reason` becomes each thread's `reply_markdown` + `note`,
  exactly as `fix` synthesizes per-item `summary`/`why` from one reason
  (`core/workflow.py:784-793`).

### Mode matrix (resolve)

| Flags | Resolution | Requires commit | Requires homogeneous bodies |
|---|---|---|---|
| `<item_id> --commit …` | fix (single) | yes | n/a |
| (no id) `--commit --homogeneous-reason` | fix (match-all) | yes | yes |
| (no id) `--reject --homogeneous-reason --match-files` | reject (match-all) | **no** | yes |
| (no id) `--clarify --homogeneous-reason --match-files` | clarify (match-all) | **no** | yes |
| `--batch --input` | mixed (per-item) | per-item | no |

## 5. Behavioral requirements

- **R1** `--reject`/`--clarify` are mutually exclusive with each other and with the
  fix match-all path (`--commit`); conflict returns `CONFLICTING_RESOLVE_MODE`.
- **R2** Decline match-all requires `--match-files` (file-scoped, symmetric with
  `--stale`) and `--homogeneous-reason`; missing either fails fast with a clear
  reason code and next-action.
- **R3** Eligibility gate: all matched, claimable threads must share identical
  first-body text. If not, reject the run and route to the per-thread batch
  skeleton (reuse `FIX_ALL_PER_THREAD_EVIDENCE_REASON` semantics) — never decline
  heterogeneous threads with one reason.
- **R4** Stale/outdated matches route to the stale path, same as fix
  (`_enforce_fast_fix_routing`).
- **R5** Each matched thread records `classification=reject|clarify`, issues the
  decline action request, and submits its **own per-thread `ActionResponse`** (via
  `agent_protocol.submit_action_response`) with `reply_markdown` + `note` = the shared
  rationale. Decline does **not** use the BatchActionResponse channel (that channel is
  fix-only); the threads are looped and submitted individually. Partial failures surface
  per-row like the fix path.
- **R6** `--publish` publishes accepted decline replies; absent it, the next action
  points to `agent publish`.
- **R7** Final-gate authority unchanged: declined threads count as resolved evidence
  exactly as a per-thread decline would.

## 6. Secondary: stable lean aliases

- **R8** `--lean` output assigns each thread a short stable alias (e.g. `T1`, `T2`,
  ordered deterministically by file then thread creation) alongside the full
  `item_id`.
- **R9** `agent resolve` (single-item mode) accepts the alias in place of an
  `<item_id>` and resolves it to the canonical id within the session; ambiguous/expired
  aliases fail with guidance to re-run `--lean`. Extending alias resolution to other
  item-id-taking commands (`agent classify`, `agent next`, …) is **out of scope** for this
  change and tracked as follow-up.

## 7. Acceptance scenarios

1. 8 same-file, identical-body auto-reviewer nits → one
   `agent resolve --reject --homogeneous-reason … --match-files` accepts all 8;
   `agent publish` posts 8 identical decline replies; final-gate passes.
2. Same files but **two distinct** bodies → run is rejected before any acceptance,
   with next-action pointing at the per-thread batch skeleton.
3. `--reject` together with `--commit` → `CONFLICTING_RESOLVE_MODE`.
4. `--clarify` without `--match-files` → fails fast with `MISSING_MATCH_FILES`-style
   reason.
5. Stale thread in the match set → routes to the `--stale` path.
6. Lean alias `T3` used in place of the full id → resolves to the correct thread;
   a stale alias after re-sync → actionable error.

## 8. Open questions

- Should `--clarify` (which keeps the thread open for reviewer follow-up) be allowed
  in the homogeneous collapse, or restricted to `--reject` only? (Default: allow
  both; clarify replies are still per-thread posts, just sharing body text.)
- Alias namespace: per-session ephemeral (`T1…Tn`) vs. derived from a short hash of
  the node id. Ephemeral index is easier to read but changes across `--lean` runs;
  short hash is stable but less human-friendly. Lean toward ephemeral index with the
  full id always echoed.
