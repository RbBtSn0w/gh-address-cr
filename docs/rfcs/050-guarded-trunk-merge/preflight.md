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

## Authenticated reply identity

The existing runtime requires durable reply evidence from its authenticated
account. Retain that contract and its original GitHub adapter unchanged. A
separately configured read-only BRANCH_GATE_TOKEN selects the actual user that
provided replies; task read credentials and the merge App serve other roles.
No dispatch actor/environment login is substituted for authentication. Missing
credentials block both summary readiness and merge with a named diagnostic.

## Bounded merge IO

A job-level execution deadline starts before setup and expires two minutes before
the runner's ten-minute timeout. Merge PUT uses a short subprocess timeout;
reads are capped by remaining budget, with enough time reserved for reconciliation
and artifact output. An exhausted budget blocks before PUT. Actual transport
timeout is tested, not merely an immediate synthetic exception.

## Existing App permission inventory

The live release App exposes checks/statuses read and contents/PR write, but no
Actions permission. Retain these grants: read CI/run/artifact facts using the
job read-only token, evaluate the unchanged runtime gate using BRANCH_GATE_TOKEN,
and use the event-capable App only for the merge mutation. None of these
credentials is replaced by an operator name. The source subprocess credential
filter strips read and gate tokens. Regression
coverage checks reads and mutation requests use their respective credentials.

## Live workflow identity contract

The live run API returns dynamic run-name text in name as well as display_title.
Never use either as workflow identity. Automatic consumers reread the run and
its canonical workflow ID/path; sync proposals additionally accept only same-repo
Release push/dispatch completions on main. Display-name lists remain subscription
filters only. This removes display-title variants from the authorization policy.

## Reply-evidence identity refinement approved during implementation

The existing runtime deliberately requires durable replies by its authenticated
viewer. Installation identity alone does not provide another account's reply
authorization. The owner explicitly chose a new BRANCH_GATE_TOKEN configuration
entry rather than changing final-gate truth: GitHub job token reads CI facts,
read-only user gate token evaluates replies/checks, existing App merges. Missing
gate credentials block named workflow paths without identity fallback. No token
is provisioned or repository setting changed by this implementation. The gate
account must actually provide required reply evidence; actor names never stand
in for authentication. All three credential classes are stripped from source
subprocesses, except the exact trusted runtime invocation receives its gate token.

Official analyzer/preset direct dependencies are fixed at the locally and CI
verified 13.0.1/10.4.1 on Node 24, consistently across analysis/tests/publication.
Policy-change detection uses local git diff limited to trusted policy paths,
removing the prior first-page file-count limit without a new resolver or store.

History synchronization remains proposal-only after successful Release runs,
including validation-only/no-version runs. Main code changes still need their
history synchronized; proposal text must not label those runs as published.
The projection separately observes publication, and operator approval is required
before every merge. No new production-only auto-sync policy is introduced.
