# Quickstart: Workflow Gap Recovery Validation

## Prerequisites

- From repo root, install the package in editable mode:

```bash
pip install -e .
```

- Use the current feature branch:

```bash
git branch --show-current
```

Expected result: `028-workflow-gap-recovery`

## Scenario 1: Terminal thread reply-evidence recovery

Validate that a closed-thread reply-evidence gap has a supported reconcile path.

```bash
python3 -m unittest tests.test_issue142_stale_lease_deadlock.Issue142ReplyEvidenceIngestTest
python3 -m unittest tests.test_final_gate
```

Expected outcomes:

- Reply evidence can be recorded for a terminal GitHub thread.
- `final-gate` no longer points only to a dead-end publish loop for reconcile-only blockers.
- The supported reconcile command is `gh-address-cr agent evidence add <owner/repo> <pr_number> --item-id <item_id> --reply-url <reply_url> --author-login <login>`.

## Scenario 2: Terminal thread validation-evidence recovery

Validate that a resolved fix thread can be reconciled without reopening claim paths.

```bash
python3 -m unittest tests.test_resolved_thread_validation_gap
```

Expected outcomes:

- Terminal validation evidence reconcile succeeds for success-like validation.
- Open threads remain rejected from reconcile-only flow.

## Scenario 3: Lease-owned item recovery diagnostics

Validate that batch-claimed or active-lease states surface deterministic recovery guidance.

```bash
python3 -m unittest tests.test_issue142_stale_lease_deadlock
python3 -m unittest tests.test_agent_resolve_guards
```

Expected outcomes:

- Self-held stale fixer leases can recover through the supported stale path.
- Non-self or non-fixer leases remain protected.
- Item-mode guardrails stay fail-fast where mode mixing is unsupported.
- When an item is blocked by an active lease, the runtime reports `LEASE_LOCKED_ITEM` plus lease-owner recovery details instead of a generic `NO_ELIGIBLE_ITEM`.

## Scenario 4: Completion guidance for local telemetry

Validate that local `runtime-only` coverage is treated as advisory and still reported explicitly.

```bash
python3 -m unittest tests.test_final_gate
python3 -m unittest tests.test_python_wrappers
```

Expected outcomes:

- Completion summaries still report `runtime-only`.
- `runtime-only` local coverage is treated as advisory rather than an abnormal completion alert by itself.
- Human guidance distinguishes advisory local coverage from malformed telemetry.

## Scenario 5: Wrapped GitHub permission diagnostics

Validate preflight classification for GitHub CLI permission failures and related environment distinctions.

```bash
python3 -m unittest tests.test_native_foundation
python3 -m unittest tests.test_runtime_packaging
```

Expected outcomes:

- Machine-readable diagnostics distinguish auth, network, sandbox/environment,
  and the new permission-mismatch path.
- Wrapped `gh` permission drift reports `GH_PERMISSION_MISMATCH`, `github_permission`, and a wrapper-scoped diagnostic source.

## Full Verification Stack

Run the repository completion checks after implementation:

```bash
pip install -e .
ruff check src tests scripts/build_plugin_payload.py
python3 -m unittest discover -s tests
python3 -m gh_address_cr --help
python3 -m gh_address_cr agent manifest
python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr
python3 scripts/build_plugin_payload.py --check
```

Expected outcome: all checks pass with runtime and skill docs aligned to the
updated recovery behavior.
