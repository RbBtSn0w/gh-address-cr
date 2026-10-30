# Architecture Preflight: Agent-neutral evaluation runner

## Decision and scope

The evaluation harness must not choose an agent vendor, model, account, skill
installation convention, permission policy, or transcript dialect. Replace its
Claude-specific launch and reporting integration with a versioned external
command boundary. Keep the offline scripted reference, fixtures, fake GitHub,
and deterministic graders. This changes repository development tooling, not the
installed runtime or packaged agent protocol version.

| Preflight boundary | Decision |
| --- | --- |
| Authoritative state | Each existing evaluation fixture's runtime store, bare PR remote and fake GitHub state continue to own handling facts. The harness owns result records and their independent grading. |
| Inputs | Explicit `--agent scripted` or `--agent external --runner <config.json>`. `finding-eval-runner.v1` config provides an argv array; no shell expansion or provider defaults. |
| Structured request | `finding-eval-request.v1` JSON on runner stdin identifies the fixture repo/PR, the task, and the fixture-local skill snapshot path. The command runs in that fixture checkout with its existing isolated environment. |
| Structured result | `finding-eval-result.v1` JSON on runner stdout provides bounded identity/step observations and optional cost. Unknown or malformed fields fail explicitly; no vendor transcript parsing or default identity inference. |
| Projection and policy | Runner metadata is self-reported diagnostic evidence. Existing graders independently decide legal state, effective fix and evidence consistency from the fixture, including failures and early exits. Runner success cannot make a failed grade pass. |
| Side-effect boundary | The explicitly configured executable runs through the existing process-group timeout/cleanup boundary. Its tools must stop before grading. It receives the fake GitHub environment; the harness never adds real GitHub credentials. |
| Artifact truth | The harness writes request/result, local process output and grade artifacts. Raw output is local diagnostic material and is not copied into public summaries. Result rows never become authoritative review state. |
| Recovery | Keep failed attempts, costs when valid, and fixtures when requested. Rerendering reports reads normalized observations; it does not reinterpret vendor logs or rerun grading. New comparisons use consistent runtime/grader/runner settings and differ only in skill snapshots. |

## Contract and privacy constraints

Install the skill under `.eval/skill`, excluded from fixture commits, and pass
that path explicitly. An executor may expose the snapshot to its chosen host;
the harness does not install host-specific directories or slash commands.
Keep the existing credential and Git-location environment scrubbing; provider
marker names may remain in that denylist because filtering is not a provider
integration. Never include raw argv, input prompts, stdout/stderr, filesystem
paths, identities or tokens in OTel. Observe the external process only with its
executable basename, PID, exit code, bounded failure category and outcome.

The config and result parsers have bounded input sizes. Reject unsupported
versions, unexpected fields, missing commands, malformed step entries,
non-finite/negative cost and invalid identity metadata. Record process failures
or protocol failures explicitly. Do not silently synthesize a successful agent
result from empty or invalid output. A timeout remains a failed attempt and the
existing cleanup boundary must terminate its tools before grading.

The public tooling contract deliberately removes `--agent claude`, `--model`,
`--max-turns`, `--max-budget-usd`, and `--allowed-tools`; executor-specific
choices belong to its argv/configuration outside the harness. Old invocations
fail loudly. Historical result rows may still be summarized as stored facts,
but raw historical transcripts are not reparsed through hidden vendor shims.

## Verification and execution intent

First prove RED: a local fake external executable should receive the structured
request and return normalized steps without requiring an agent SDK/account;
the current CLI rejects that execution mode. Then implement the smallest
external boundary and verify GREEN. Use executable subprocess tests for request
delivery, cwd/environment, skill snapshot isolation, valid and malformed JSON,
unsupported fields/versions, missing/oversized output, exit failures, timeout
and process cleanup. Verify old flags fail and public help has no fixed model
or vendor invocation. Run all five scripted reference samples and the existing
grading controls, then the repository's required lint/type/unit/smoke/payload
checks.

This is not a new review producer, orchestration queue or plugin registry. A
generic command boundary is sufficient; replacing one hardcoded vendor with
another is explicitly rejected. Scripted controls validate the harness and
must not be reported as evidence of improved real-agent behavior in PR #374.
No external vendor account is a prerequisite for implementing issue #365.

## Fixture concurrency correction

Independent delivery verification exposed a control run with a passing gate but
no current PR head observation. The runtime performs parallel GitHub reads;
the fake refreshed its shared JSON using a truncate/write cycle on every call.
A controlled slow-writer regression reproduces another reader receiving invalid
JSON. Serialize the complete fake call, including delegated state reads and
mutations, with one fixture-local file lock. This changes only fixture IO, not
runtime policy, grading criteria, or provider integration. The regression must
pass alongside the five reference samples before real comparison runs begin.
