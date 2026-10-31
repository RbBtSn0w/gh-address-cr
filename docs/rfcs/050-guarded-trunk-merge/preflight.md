# Guarded trunk merge and readiness preflight

Status: implementation authorized; activation and real merges are not authorized.
Date: 2026-10-31

## Authority and inputs

GitHub refs, PRs, workflow runs/jobs/artifacts and explicit workflow-dispatch
inputs are external facts. The existing gh-address-cr runtime owns review and
final-gate truth. Repository release helpers own no new authoritative store.
Supported directions are develop -> main and verified main snapshot -> develop.
Approval comes only from an admin/maintain operator's explicit dispatch, exact
head/base, matching consequence confirmation and cooperative-writer-pause expiry.
PR text, summaries and artifacts never authorize a merge.

## Projection and policy

Readiness projects current refs, named source checks, review-gate output, CI
validation context, version analysis and publication observations. A bounded
policy returns ready/blocked/unavailable. A versioned CI context is producer
execution evidence, verified against GitHub run/attempt, job success and actual
merge parents; it is not a second review state machine. GitHub run PR links may
be empty, so this small producer receipt is necessary to prove tested base/head.
Metadata-only runs cannot produce it. Source or policy uncertainty fails closed.
Advisory readiness excludes its own check wait; actual merging uses the unchanged
runtime final-gate with all checks required.

## Side effects and recovery

Readiness may replace only its own validated PR-body block and emit JSON/job
summaries. Semantic equality suppresses write loops. Privileged execution checks
out immutable trusted main code, never candidate code. Real external commands
reuse existing CLIENT spans and fail-open telemetry; CLI roots are INTERNAL.
No raw argv, paths, PR text, log output or credentials enter telemetry.

Merge requests always use merge_method=merge, a clean generated message and an
expected-head guard. Base is reread immediately before the request. GitHub has
no atomic expected-base option, so cooperative writer pause remains a limitation,
not a fabricated technical lock. Actual merge parents, retained refs and ancestry
are verified afterwards. Ambiguous IO is reconciled by read, never blind retry;
anomalous completed merges are reported without rollback/history rewriting.
Only existing event-capable Bot credentials are accepted for merge. No fallback
to GITHUB_TOKEN, protection bypass, settings change or unattended merge is added.

## Verification and rollout

Isolated Git/API fixtures cover event/permission routing, CI context binding,
source/metadata isolation, stale approvals, snapshot provenance, clean messages,
summary ownership, timeout reconciliation, idempotence and post-merge anomalies.
Privacy and telemetry failure remain executable contracts. Full repository gates,
actionlint, a develop PR and fresh CI/review evidence precede delivery. Read-only
inspection of #396 is allowed; no writes/merges/dispatches for #396 or publication
are part of implementation. Five top-level workflows remain. Default-main
activation and actual guarded merge acceptance require separate future approval.

## Authenticated identity compatibility discovered during review

The existing REST GET /user lookup cannot identify an installation credential,
so it cannot support the approved existing-App path. Replace that internal
lookup with GitHub's documented GraphQL viewer { login } for user and App
credentials alike. GitHub remains the source of authenticated identity; no
operator/env login is substituted. Public CLI, runtime state and final-gate
truth/attribution rules are unchanged. Regression fixtures cover actual bot/user
viewer responses, errors, malformed identity and caching. Reference:
https://docs.github.com/en/enterprise-cloud@latest/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation

## Bounded merge IO

A job-level execution deadline starts before setup and expires two minutes before
the runner's ten-minute timeout. Merge PUT uses a short subprocess timeout;
reads are capped by remaining budget, with enough time reserved for reconciliation
and artifact output. An exhausted budget blocks before PUT. Actual transport
timeout is tested, not merely an immediate synthetic exception.

## Existing App permission inventory

The live release App exposes checks/statuses read and contents/PR write, but no
Actions permission. Retain these grants: read CI/run/artifact facts and the
review gate using the job read-only token; use the event-capable App token only
for the merge mutation. Neither token is replaced by an operator name. The
source subprocess credential filter also strips the read token. Regression
coverage checks reads and mutation requests use their respective credentials.
