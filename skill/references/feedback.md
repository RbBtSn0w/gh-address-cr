# Feedback Workflow

When the skill itself blocks progress, file a feedback issue against the skill repository before giving up.

## Contents

- Automatic feedback on skill exceptions
- Feedback command fields
- Examples

By default, feedback issues are filed to `RbBtSn0w/gh-address-cr`. Override `--target-repo` only when the skill owner explicitly directs you to use a different feedback repository.

Use feedback issues for skill-level problems:

- contradictory instructions
- missing automation
- documentation gaps
- repeatable tooling failures that are not caused by the repository under review

Do not file feedback issues for normal PR findings, code bugs in the target repository, or expected wait states such as `WAITING_FOR_EXTERNAL_REVIEW`.

## Automatic feedback on skill exceptions

File a `tooling-bug` feedback issue automatically — without waiting to be asked — whenever a
`gh-address-cr` command fails in a way that is the skill's own fault. This is the only
auto-trigger; everything else stays manual.

A failure is the skill's fault when EITHER:

- **(a) Crash** — the command printed a Python traceback or other non-JSON output and exited
  non-zero (there is no structured `status` in stdout), OR
- **(b) Structured skill error** — the JSON summary's `reason_code` **ends in `_ERROR`** (for
  example `SYSTEM_ERROR`, `SESSION_ERROR`, `PUBLISH_ERROR`). This is the same shape the
  runtime emits as `status: FAILED`, `waiting_on: session`, `exit_code: 5`.

Do **not** auto-file feedback for normal protocol, agent-input, or environment signals — none
of these end in `_ERROR`, so the two cases are cleanly separable. These are expected flow or
your own input to fix, not skill defects:

- any `*_REJECTED` (for example `ACTION_REJECTED`, `BATCH_ACTION_REJECTED`, `FAST_FIX_REJECTED`,
  `FAST_FIX_ALL_REJECTED`, `EVIDENCE_PROFILE_REJECTED`, `DECLINE_ALL_REJECTED`)
- `MISSING_*`, `CONFLICTING_*`, `PER_THREAD_EVIDENCE_REQUIRED`, `INVALID_ARGUMENTS`
- `NO_ELIGIBLE_ITEM`, `STALE_REQUEST_CONTEXT`, `LEASE_RECOVERY_STOP`, `PUBLISH_BLOCKED`
- `WAITING_*` wait states and `PR_SCOPE_UNRESOLVED`
  (`NO_ACTIVE_PR_SCOPE`/`AMBIGUOUS_PR_SCOPE`/`PARTIAL_PR_SCOPE`)
- environment lookups such as `ACTIVE_PR_LOOKUP_FAILED`, `GITHUB_INCOMPLETE_RESPONSE`,
  `MALFORMED_TELEMETRY`

If you instead suspect a skill defect behind a non-`_ERROR` failure (for example the skill
forced you off the prescribed flow, or repeated `CONFLICTING_*`/`MISSING_*` came from
contradictory instructions rather than your input), report it manually as `workflow-gap` —
do not auto-file it.

Filing is safe to do unconditionally on a qualifying failure: repeated identical exceptions
are deduplicated by fingerprint, and a recently-closed match inside the cooldown window is
suppressed, so you will not create duplicates. Sanitization is automatic, but still avoid
pasting secrets, usernames, machine names, or absolute local paths into the fields you write.

Fill the template from the diagnostics the failing command already gave you:

```bash
gh-address-cr submit-feedback \
  --category tooling-bug \
  --title "<command> crashed with <reason_code>" \
  --summary "<what you were doing when it failed>" \
  --expected "the command should complete, or return a structured, recoverable status." \
  --actual "<the _ERROR reason_code or a short traceback summary>" \
  --failing-command "<the exact gh-address-cr command that failed>" \
  --status FAILED \
  --reason-code <SYSTEM_ERROR|SESSION_ERROR|...> \
  --exit-code 5 \
  --run-id <run_id> \
  --using-repo <owner/repo> \
  --using-pr <pr_number> \
  --skill-version <version>
```

Do not include usernames, emails, tokens, machine names, or absolute local paths in feedback issues. Prefer safe technical diagnostics such as failing command, exit code, status, `reason_code`, `waiting_on`, `run_id`, and skill version.

Always provide `--using-repo` and `--using-pr` for PR-scoped feedback. When those are present, `submit_feedback.py` auto-collects local PR-workspace evidence from `last-machine-summary.json`, `session.json`, `audit_summary.md`, and cached PR head SHA when those files exist.

Repeated feedback is deduplicated by fingerprint; if the same feedback issue is already open, or was closed recently inside the cooldown window, the helper returns the existing issue instead of creating a new one.

Use `gh-address-cr submit-feedback` with explicit fields:

- `--category`
- `--title`
- `--summary`
- `--expected`
- `--actual`
- optional `--source-command`, `--failing-command`, `--exit-code`, `--status`, `--reason-code`, `--waiting-on`, `--run-id`, `--skill-version`, `--using-repo`, `--using-pr`, `--artifact`, and `--notes`

Example:

```bash
gh-address-cr submit-feedback \
  --category workflow-gap \
  --title "blocked without a recovery step" \
  --summary "review stopped in a blocked state without enough operator guidance." \
  --expected "the skill should identify the next command or artifact to inspect." \
  --actual "the workflow stopped and the next action was ambiguous." \
  --source-command "gh-address-cr review owner/repo 123" \
  --failing-command "gh-address-cr final-gate owner/repo 123" \
  --exit-code 5 \
  --status BLOCKED \
  --reason-code WAITING_FOR_FIX \
  --waiting-on human_fix \
  --run-id review-20260417T120000Z \
  --skill-version 1.2.0 \
  --using-repo owner/repo \
  --using-pr 123 \
  --artifact <loop-request.json>
```
