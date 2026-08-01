# Quickstart: Validate Stacked Pull Request Support

This guide proves each user story independently and keeps fixture, live
read-only, and live mutation evidence separate.

## Prerequisites

```bash
pip install -e .
gh auth status
```

Do not install `gh stack`, push branches, create a test repository, or merge a
stack merely to run local contract phases.

## Phase 1 — Stack Context (US1)

```bash
python3 -m unittest tests.test_stack_kernel
python3 -m unittest tests.test_stack_github_client
python3 -m unittest tests.contract.test_stacked_pr_contract.StackContextContractTests
```

Expected:

- Unstacked fixtures preserve fields and exits.
- Bottom, middle, and top report positions `1`, `2`, and `3`.
- Multi-page fixtures produce complete order.
- Unsupported schema reports `unavailable` without breaking normal layer flow.
- Invalid position, size, selection, or chain returns `STACK_CONTEXT_INVALID`
  for stack-specific evaluation.

## Phase 2 — Revision-Safe Resolution (US2)

```bash
python3 -m unittest tests.test_agent_protocol
python3 -m unittest tests.contract.test_stacked_pr_contract.RevisionBindingContractTests
```

| Initial request | Refreshed context | Expected result |
|-----------------|-------------------|-----------------|
| Same head/topology | Same | Existing response accepted |
| Upper head rebased | Different OID | `STALE_REQUEST_CONTEXT` before publish |
| Stack reordered | Different fingerprint/position | `STALE_REQUEST_CONTEXT` |
| Explicit wrong PR/head | Any | `STACK_ACTION_CONTEXT_MISMATCH` |
| Old unbound evidence on stacked member | Same | Fresh validation required |

## Phase 3 — Layer vs Stack Gate (US3)

```bash
python3 -m unittest tests.test_final_gate
python3 -m unittest tests.test_stack_final_gate
python3 -m unittest tests.contract.test_stacked_pr_contract.StackFinalGateContractTests
```

Expected sequence for three members:

1. Top layer may pass with `completion_scope=pull_request` and aggregate
   readiness `not_evaluated`.
2. `final-gate --stack` fails on the first missing/broken bottom-up member and
   names its PR plus recovery command.
3. Clearing members exposes the next blocker in bottom-up order.
4. All layer gates plus an unchanged closing fingerprint are required for
   `completion_scope=stack_segment` to pass.
5. A changed closing fingerprint returns `STACK_CONTEXT_STALE`, never a
   completion line.

## Phase 4 — Telemetry, Docs, and Privacy (US4)

```bash
python3 -m unittest tests.test_otel_telemetry
python3 -m unittest tests.test_skill_docs
python3 -m unittest tests.contract.test_stacked_pr_contract.TelemetryPrivacyContractTests
```

Events may contain bounded availability, size bucket, position class, requested
scope, outcome, and reason. Exported telemetry/public-safe reports must omit
branches, member lists, titles, bodies, paths, usernames, and fingerprints.

## Full Repository Gate

```bash
pip install -e .
ruff check src tests scripts/build_plugin_payload.py
python3 -m unittest discover -s tests
python3 -m gh_address_cr --help
python3 -m gh_address_cr agent manifest
python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr
python3 scripts/build_plugin_payload.py --check
```

All commands must pass before live acceptance.

## Live Level A — Read-Only Capability Probe

This proves authenticated schema capability, not real stack behavior:

```bash
gh api graphql -f query='{pr:__type(name:"PullRequest"){fields{name}} stack:__type(name:"PullRequestStack"){fields{name}}}'
gh --version
gh extension list
```

Record host/capability, local `gh` version, extension presence, and whether any
real stack was evaluated.

## Live Level B — Isolated Stack Discovery

Requires an existing disposable three-layer stack supplied by the maintainer.
Read-only validation:

```bash
gh-address-cr address <owner/repo> <bottom-pr> --lean
gh-address-cr address <owner/repo> <middle-pr> --lean
gh-address-cr address <owner/repo> <top-pr> --lean
```

Confirm correct order/context and no branch, thread, queue, or merge mutation.

For the authorized demo repository, provision and verify a disposable fixture
without cloning it:

```bash
python3 scripts/e2e_stacked_pr_sandbox.py provision \
  --manifest /var/tmp/gh-address-cr-stack-e2e.json
python3 scripts/e2e_stacked_pr_sandbox.py verify \
  --manifest /var/tmp/gh-address-cr-stack-e2e.json
```

## Live Level C — Mutation and Aggregate Gate

This level requires explicit authorization because creating/rebasing/pushing a
stack changes remote branches. Use a disposable repository or isolated branches
and install the official extension only if authorized.

Required evidence:

1. Initialize sessions for every member bottom-up.
2. Record passing validation for each current head.
3. Prove each layer gate reports PR scope.
4. Prove `final-gate --stack --require-required-checks` passes.
5. Change a lower test layer and explicitly cascade with GitHub stack tooling.
6. Prove upper request/evidence becomes stale before publish/completion.
7. Revalidate affected layers and prove the stack gate passes again.

Do not merge unless separately authorized; gh-address-cr support does not
require exercising GitHub's destructive merge API.

The sandbox harness automates the non-merge regression flow and is idempotent
after its review threads have been resolved:

```bash
python3 scripts/e2e_stacked_pr_sandbox.py exercise \
  --manifest /var/tmp/gh-address-cr-stack-e2e.json
```

Cleanup is explicit and manifest-scoped:

```bash
python3 scripts/e2e_stacked_pr_sandbox.py cleanup \
  --manifest /var/tmp/gh-address-cr-stack-e2e.json
```

## Evidence Report

For each phase record exact command/exit, fixture or live scope, layer versus
stack scope, mutation if any, compact final-gate line and artifact hashes,
telemetry coverage/privacy result, and remaining preview limitation.
