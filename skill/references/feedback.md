# Feedback Workflow

When the skill itself blocks progress, file a feedback issue against the skill repository before giving up.

By default, feedback issues are filed to `RbBtSn0w/gh-address-cr`. Override `--target-repo` only when the skill owner explicitly directs you to use a different feedback repository.

Use feedback issues for skill-level problems:

- contradictory instructions
- missing automation
- documentation gaps
- repeatable tooling failures that are not caused by the repository under review

Do not file feedback issues for normal PR findings, code bugs in the target repository, or expected wait states such as `WAITING_FOR_EXTERNAL_REVIEW`.

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
