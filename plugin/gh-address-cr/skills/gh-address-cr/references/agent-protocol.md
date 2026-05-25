# Agent Protocol

Use the runtime as the coordinator. AI agents must not post GitHub replies or resolve GitHub review threads directly.

## Machine Summary Contract

High-level commands emit structured JSON by default. Agents must consume these fields and must not parse human prose to determine system state:

- `status`
- `repo`
- `pr_number`
- `item_id`
- `item_kind`
- `counts`
- `artifact_path`
- `reason_code`
- `waiting_on`
- `next_action`
- `commands`
- `exit_code`
- `diagnostics`

`reason_code` is the stable machine reason. `waiting_on` is the stable wait-state category. `commands` contains executable command templates for the current PR; prefer those over reconstructing commands manually. Lean output keeps only `item_id`, `thread_id`, `path`, `line`, `state`, `status`, `is_resolved`, `is_outdated`, `claimable`, `accepted_response_present`, and `reply_evidence_present`.

## Commands

- `gh-address-cr agent manifest`
  - Discover supported roles, actions, formats, protocol versions, and `max_parallel_claims`.
- `gh-address-cr agent classify <owner/repo> <pr_number> <item_id> --classification <fix|clarify|defer|reject> --note <why>`
  - Records triage-phase evidence before a mutating fixer lease is issued.
- `gh-address-cr agent next <owner/repo> <pr_number> --role <role> --agent-id <id>`
  - Claims one eligible item and writes an `ActionRequest`.
- `gh-address-cr agent submit <owner/repo> <pr_number> --input <response.json>`
  - Validates an `ActionResponse`, lease ownership, and required evidence.
- `gh-address-cr agent submit-batch <owner/repo> <pr_number> --input <batch-response.json>`
  - Validates a `BatchActionResponse` for multiple leased GitHub review-thread `fix` items sharing common commit/files/validation evidence.
- `gh-address-cr agent evidence add <owner/repo> <pr_number> --name <profile> --commit <sha> --files <paths> --validation <cmd=passed> [--severity P1|P2|P3 --severity-note <why>]`
  - Records reusable commit/files/validation evidence for later `evidence_ref` use.
- `gh-address-cr agent fix <owner/repo> <pr_number> <item_id> --commit <sha> --files <paths> --summary <text> --why <text> --validation <cmd=passed> [--severity P1|P2|P3 --severity-note <why>] [--publish]`
  - Classifies, claims, submits, and optionally publishes one straightforward GitHub-thread fix.
- `gh-address-cr agent fix-all <owner/repo> <pr_number> --commit <sha> --files <paths> --validation <cmd=passed> [--severity P1|P2|P3 --severity-note <why>] [--publish] [--include-stale]`
  - Classifies, claims, and submits safe batches for matching GitHub-thread items already present in the runtime session.
- `gh-address-cr agent resolve-stale <owner/repo> <pr_number> --commit <sha> --files <paths> --validation <cmd=passed> --match-files [--severity P1|P2|P3 --severity-note <why>] [--publish]`
  - Handles matching `STALE` or outdated GitHub-thread items through evidence, leases, publish, and final-gate. It never marks stale threads resolved directly.
- `gh-address-cr agent leases <owner/repo> <pr_number>`
  - Inspects active and terminal claims.
- `gh-address-cr agent reclaim <owner/repo> <pr_number>`
  - Expires stale leases without deleting accepted evidence.

## Evidence Rules

Classification is triage-phase evidence. Resolution is response-phase evidence. Do not satisfy `MISSING_CLASSIFICATION` by adding a `resolution` field to a response file; run `agent classify` first. Do not satisfy `MISSING_RESOLUTION` by reclassifying the item; add `resolution` to the `ActionResponse` and rerun `agent submit`.

Allowed `ActionResponse.resolution` values are `fix`, `clarify`, `defer`, and `reject`.

For GitHub thread `fix`, `fix_reply` **must be a JSON object**, not a string. Submitting a plain string may pass `agent submit` but will block `agent publish` with `MISSING_PUBLISH_REPLY`. Required fields: `commit_hash`, `files`, `summary`. Optional fields: `severity`, `why`, `test_command`, `test_result`. If `test_command` and `test_result` are omitted, `validation_commands` at the response level is used as default validation evidence.

Severity is evidence-backed. The runtime stores `P1`, `P2`, or `P3` only when the marker is explicit in the producer payload or in the original GitHub review-thread comment. Missing severity remains unknown, and published fix replies omit the `Severity:` line. Reviewer `high`, `medium`, and `low priority` markers are preserved as raw priority evidence but are not mapped to P-scale severity. A fix response may include explicit `fix_reply.severity`; if it conflicts with first-scene severity evidence, include `fix_reply.severity_note` or the response is rejected with `SEVERITY_OVERRIDE_NOTE_REQUIRED`.

Clarify, defer, and reject responses require `reply_markdown` and validation evidence. GitHub side-effect claims from AI agents are invalid.

For `--validation`, use `<command>=<result>` when you need a result other than the default `passed`. Values without an explicit result suffix are treated as the full command, so environment assignments like `PYENV_VERSION=3.10.19 python -m unittest` are preserved.

## Batch Notes

`BatchActionResponse` is limited to GitHub review-thread `fix` evidence with existing per-item leases; it is not a GitHub publishing shortcut and does not support local findings. Prefer `agent fix-all` when one commit/files/validation set addresses multiple already-synced GitHub threads.

`agent next` emits both `request_path` and `response_skeleton_path`. Prefer filling the skeleton instead of hand-writing `ActionResponse` JSON. Required user-supplied fields are intentionally empty so an unedited skeleton is rejected instead of published.
