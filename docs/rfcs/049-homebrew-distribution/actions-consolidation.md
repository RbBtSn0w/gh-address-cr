# ADR: Consolidate Actions into five operational workflows

Status: Accepted for implementation; activation requires reviewed main promotion.
Date: 2026-10-31

## Decision and preflight

Combine target-branch validation with Python checks, and combine release/sync
proposals in Branches. Keep Preview, Release and Homebrew separate. This removes
two workflow registrations without changing publication or merge authority.
Seven-file status quo retains redundant navigation; a three-file controller adds
conditional routing and couples preview trust and recovery, so both are rejected.

Git refs, GitHub PRs/checks and immutable release assets remain authoritative.
Inputs are PR events, trunk pushes, schedules, explicit dispatch operations and
successful main Release workflow completion. Job-level event predicates select
exactly one proposal operation; unknown dispatch operations select neither.
Branches has no runtime store. Jobs retain separate permissions/concurrency and
execute the existing proposal guards. No automatic merge or trunk mutation is
added. Same-version Homebrew recovery and all-four bottle gates are unchanged.

Proposal bodies and run summaries are evidence, not approval or authoritative
state. Replays retain idempotent PR updates and create-only, parent/tree-validated
sync snapshots; missing trunks or drift fail closed. Existing release governance
and writer coordination continue to apply.

Checks retains the trusted ci.yml producer path. Rename its display name to
Checks / Python only because the published main preview consumer already accepts
that staged name; retain both producer names for older PRs. Release completion
consumers accept both historical and new display names during migration. Do not
remove historical run evidence or change GitHub-managed workflow settings.

Tests cover proposal event routing, isolated permissions, immutable sync behavior,
branch validation including base edits, producer/consumer names, five-file scope,
and unchanged preview credentials and four-target publication gates. Existing
executable shell fixtures continue to run the actual proposal steps. Actionlint,
full repository checks and fresh PR CI/review are required before delivery.

## Presentation and scope

Sidebar entries describe operator intents; run names identify target and action;
job names describe phases. Existing check identifiers stay stable. This pass does
not restructure the Python matrix or reduce installed-package acceptance coverage.
No new orchestration framework or telemetry protocol is introduced; live release
helper instrumentation remains attached to its existing operations.
