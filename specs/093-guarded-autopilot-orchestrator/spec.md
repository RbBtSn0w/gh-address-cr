# Feature Spec: Guarded Autopilot Orchestrator Mode

## Summary

Add a guarded autopilot planning mode without enabling default GitHub side effects.

## Behavior

- `agent orchestrate autopilot <owner/repo> <pr_number>` emits a deterministic dry-run plan.
- The plan covers classify, lease, submit, publish, and final-gate steps.
- Side-effecting execution is rejected in this v1 contract.
- Existing orchestrator start/step/status/submit/stop behavior remains unchanged.

## Owner Boundary

Runtime orchestrator code owns planning and side-effect guardrails. Skill prose only routes agents to the command.

## Verification

- `python3 -m unittest tests.test_issue78_agent_experience.Issue78AutopilotTests`
- `python3 -m unittest tests.test_lease_scheduling`
- `ruff check src tests`
- `python3 -m unittest discover -s tests`
- `python3 -m gh_address_cr --help`
