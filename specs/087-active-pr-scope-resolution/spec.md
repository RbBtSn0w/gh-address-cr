# Feature Spec: Resolve PR Scope From Active Cached Sessions

## Summary

Allow eligible PR-scoped commands to omit `<owner/repo> <pr_number>` when exactly one cached PR session exists.

## Behavior

- Explicit repo and PR arguments remain authoritative.
- A single cached `session.json` resolves the missing PR scope.
- No cached session fails with `NO_ACTIVE_PR_SCOPE`.
- Multiple cached sessions fail with `AMBIGUOUS_PR_SCOPE` and list candidates.

## Owner Boundary

Runtime CLI scope resolution owns this behavior. Skill prose may describe it, but must not guess session state.

## Verification

- `python3 -m unittest tests.test_issue78_agent_experience.Issue78ActiveScopeTests`
- `ruff check src tests`
- `python3 -m unittest discover -s tests`
- `python3 -m gh_address_cr --help`
