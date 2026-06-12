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
- `handling_boundary`

`reason_code` is the stable machine reason. `waiting_on` is the stable wait-state category. `commands` contains executable command templates for the current PR; prefer those over reconstructing commands manually. Lean output keeps only `item_id`, `thread_id`, `path`, `line`, `state`, `status`, `is_resolved`, `is_outdated`, `claimable`, `accepted_response_present`, and `reply_evidence_present`.

## Commands

- `gh-address-cr agent manifest`
  - Discover supported roles, actions, formats, protocol versions, and `max_parallel_claims`.
- `gh-address-cr agent classify <owner/repo> <pr_number> <item_id> --classification <fix|clarify|defer|reject> --note <why>`
  - Records triage-phase evidence before a mutating fixer lease is issued.
- `gh-address-cr agent next <owner/repo> <pr_number> --role <role> --agent-id <id>`
  - Claims one eligible item and writes an `ActionRequest`.
- `gh-address-cr agent next <owner/repo> <pr_number> --batch --agent-id <id>`
  - Claims eligible non-stale GitHub review-thread `fix` items for the agent and writes a fillable `BatchActionResponse` skeleton.
- `gh-address-cr agent submit <owner/repo> <pr_number> --input <response.json>`
  - Validates an `ActionResponse`, lease ownership, and required evidence.
- `gh-address-cr agent submit-batch <owner/repo> <pr_number> --input <batch-response.json>`
  - Validates a `BatchActionResponse` for multiple leased GitHub review-thread `fix` items sharing common files/validation evidence while preserving per-thread summary/why.
- `gh-address-cr agent evidence add <owner/repo> <pr_number> --name <profile> --commit <sha> --files <paths> --validation <cmd=passed> [--severity P0|P1|P2|P3|P4 --severity-note <why>]`
  - Records reusable commit/files/validation evidence for later `evidence_ref` use.
- `gh-address-cr agent fix <owner/repo> <pr_number> <item_id> --commit <sha> --files <paths> --summary <text> --why <text> --validation <cmd=passed> [--severity P0|P1|P2|P3|P4 --severity-note <why>] [--publish]`
  - Classifies, claims, submits, and optionally publishes one straightforward GitHub-thread fix.
- `gh-address-cr agent trivial-fix <owner/repo> <pr_number> <item_id> --commit <sha> --files <paths> --summary <text> --why <text> --validation <cmd=passed> [--publish]`
  - Narrow shortcut for documentation or typo-only GitHub threads. Non-trivial or sensitive threads fail with `TRIVIAL_THREAD_NOT_ELIGIBLE`.
- `gh-address-cr agent fix-all <owner/repo> <pr_number> --input <batch-response.json> [--publish]`
  - Routes explicit per-thread batch evidence through the same lease and validation contract as `agent submit-batch`.
- `gh-address-cr agent fix-all <owner/repo> <pr_number> --commit <sha> --files <paths> --validation <cmd=passed> --homogeneous-reason <why> [--concern-label <label>] [--severity P0|P1|P2|P3|P4 --severity-note <why>] [--publish]`
  - Classifies, claims, and submits the homogeneous repeated-concern shortcut for matching GitHub-thread items already present in the runtime session.
- `gh-address-cr agent resolve-stale <owner/repo> <pr_number> --commit <sha> --files <paths> --validation <cmd=passed> --match-files [--severity P0|P1|P2|P3|P4 --severity-note <why>] [--publish]`
  - Handles matching `STALE` or outdated GitHub-thread items through evidence, leases, publish, and final-gate. It never marks stale threads resolved directly.
- `gh-address-cr agent leases <owner/repo> <pr_number>`
  - Inspects active and terminal claims.
- `gh-address-cr agent reclaim <owner/repo> <pr_number>`
  - Expires stale leases without deleting accepted evidence.
- `gh-address-cr telemetry ingest <owner/repo> <pr_number> --source <source> --format agent-jsonl --input <path>|-`
  - Imports safe PR-scoped telemetry from a generic agent or host-specific adapter. This does not mutate review item state.
- `gh-address-cr telemetry ingest <owner/repo> <pr_number> --source codex --format codex-host-json --input <path>|-`
  - Imports safe aggregate Codex host exports such as tokens, tool usage, duration, and status into the same canonical event model.
- `gh-address-cr telemetry summary <owner/repo> <pr_number> [--format json|markdown]`
  - Emits the combined runtime and imported telemetry efficiency report with a coverage label and report artifact path.
- `gh-address-cr command-session --input <commands.json>|-`
  - Executes multiple one-shot runtime commands in one process and emits a discrete result for every operation.
- `gh-address-cr agent orchestrate autopilot <owner/repo> <pr_number>`
  - Emits a guarded dry-run plan for triage, leasing, submission, publish, and final-gate steps. Side-effecting execution is not enabled by default.

Final-gate also supports a host integration hook. If `GH_ADDRESS_CR_HOST_TELEMETRY_INPUT` points to a safe JSONL feed, `gh-address-cr final-gate` imports that feed before writing `audit_summary.md` and `efficiency-report.json`. `GH_ADDRESS_CR_HOST_TELEMETRY_SOURCE` defaults to `assistant-host`, and `GH_ADDRESS_CR_HOST_TELEMETRY_FORMAT` defaults to `agent-jsonl`.

## Telemetry Event Contract

Generic agent telemetry uses JSONL. Each line is one event with these required fields: `source`, `kind`, `operation`, `status`, and either `duration_ms` or both `started_at` and `ended_at`. Recommended fields are `schema_version`, `source_session_id`, `event_id`, `metadata`, and `correlation_id`.

Supported `kind` values are `tool_call`, `command`, `wait`, `retry`, `validation`, and `agent_step`. Supported `status` values are `success`, `failure`, `timeout`, `cancelled`, and `unknown`.

Telemetry must be public-safe before import. Do not include tokens, credentials, raw prompts, usernames, private machine identifiers, or unnecessary absolute local paths. The runtime computes `event_fingerprint` after canonical normalization and uses it as the authoritative duplicate key. Duplicate or overlapping imports must appear in `duplicate_fingerprints` and must not inflate report counts, durations, or slowest-operation rankings.

Coverage labels are `complete`, `partial`, `runtime-only`, and `unavailable`. Missing host telemetry is a coverage fact, not a final-gate failure by default.

## Workflow Decision JSON

Structured triage handoff may use `workflow_decision.v1` JSON:

```json
{
  "schema_version": "workflow_decision.v1",
  "request_id": "req-123",
  "item_id": "github-thread:abc",
  "decision": "fix",
  "reason": "Reviewer identified a documentation typo."
}
```

Valid `decision` values are `fix`, `clarify`, `defer`, and `reject`. Missing fields, unsupported decisions, or unsupported schema versions fail fast before session state is mutated. Existing Markdown decision blocks remain compatibility guidance; JSON is the preferred machine contract.

## Evidence Rules

Classification is triage-phase evidence. Resolution is response-phase evidence. Do not satisfy `MISSING_CLASSIFICATION` by adding a `resolution` field to a response file; run `agent classify` first. Do not satisfy `MISSING_RESOLUTION` by reclassifying the item; add `resolution` to the `ActionResponse` and rerun `agent submit`.

Allowed `ActionResponse.resolution` values are `fix`, `clarify`, `defer`, and `reject`.

`agent next` and the written `ActionRequest` may include an additive `handling_boundary` object for migrated work item types. For the first migrated GitHub review-thread fix path, `boundary_id` is `github-thread-fix`; `required_evidence` lists the evidence categories the runtime expects; `completion_criteria` lists the runtime-owned completion checks; `terminal_failure_reasons` lists stable reason codes; and `next_action` points to the next runtime-mediated action. Absence of `handling_boundary` means the item is on an unmigrated compatibility path, not that agents may bypass leases, evidence, publish, or final-gate.

For GitHub thread `fix`, `fix_reply` **must be a JSON object**, not a string. Submitting a plain string may pass `agent submit` but will block `agent publish` with `MISSING_PUBLISH_REPLY`. Required worker fields: `files`. Optional fields: `commit_hash`, `summary`, `severity`, `why`, `test_command`, `test_result`. If `commit_hash` is omitted, `agent publish` hydrates commit evidence from the session or current Git `HEAD`; if no commit evidence is available, publish blocks with `MISSING_FIX_REPLY_COMMIT_HASH`. If `test_command` and `test_result` are omitted, `validation_commands` at the response level is used as default validation evidence. For `P0` and `P1` severities, `why` SHOULD contain a rich technical rationale (at least two paragraphs or 150+ characters).

Review signal is evidence-backed. The runtime stores `P0`, `P1`, `P2`, `P3`, or `P4` severity only when the marker is explicit in the producer payload or in the original GitHub review-thread comment. Reviewer `high`, `medium`, and `low priority` markers are preserved as raw priority evidence and are not mapped to P-scale severity. Published fix replies show exactly one canonical `Review signal:` line for either trusted P-scale severity or raw reviewer priority, and omit the line when neither signal is present. A fix response may include explicit `fix_reply.severity`; if it conflicts with first-scene severity evidence, include `fix_reply.severity_note` or the response is rejected with `SEVERITY_OVERRIDE_NOTE_REQUIRED`.

Clarify, defer, and reject responses require `reply_markdown`. GitHub side-effect claims from AI agents are invalid. Efficiency telemetry is reported through `final-gate`, `audit_summary.md`, and structured efficiency reports, not appended to individual GitHub review-thread replies; agents must not manually add telemetry summaries to PR thread comments.

For `--validation`, use `<command>=<result>` when you need a result other than the default `passed`. Values without an explicit result suffix are treated as the full command, so environment assignments like `PYENV_VERSION=3.10.19 python -m unittest` are preserved.

## Batch Notes

`BatchActionResponse` is limited to GitHub review-thread `fix` evidence with existing per-item leases; it is not a GitHub publishing shortcut and does not support local findings. Prefer `agent submit-batch` when one files/validation set addresses multiple already-synced GitHub threads, and keep per-thread summary/why entries for reviewer-facing replies. Commit evidence is a publish-time hydration input, not a worker-submit prerequisite. Use `agent fix-all` only with `--input <batch-response.json>` or with `--homogeneous-reason <why>` for a homogeneous repeated concern. When `fix-all` returns `PER_THREAD_EVIDENCE_REQUIRED`, run `agent next --batch --agent-id <id>` to create the batch leases and skeleton instead of hand-writing the JSON shape.

`agent next` emits both `request_path` and `response_skeleton_path`. Prefer filling the skeleton instead of hand-writing `ActionResponse` JSON. Required user-supplied fields are intentionally empty so an unedited skeleton is rejected instead of published.
