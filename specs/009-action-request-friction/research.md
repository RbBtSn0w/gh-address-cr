# Research: Action Request Friction Repair

## Decision: Accept runtime `repository_context` in helper request parsing

**Rationale**: Runtime-generated `ActionRequest` artifacts carry `repo` and `pr_number` under `repository_context`. Requiring top-level fields creates a protocol split between the deterministic runtime and packaged skill helper.

**Alternatives considered**:

- Change runtime to duplicate top-level fields. Rejected because it broadens the runtime schema for a helper compatibility issue.
- Deprecate the helper immediately. Rejected because the helper remains documented for manual continuation and is useful when agents need a response artifact generator.

## Decision: Generate formal `ActionResponse` artifacts for runtime requests

**Rationale**: `agent submit` expects response fields such as `request_id`, `lease_id`, and `agent_id`. A helper that emits only legacy loop action fields cannot safely satisfy the structured agent protocol.

**Alternatives considered**:

- Resume only old loop commands with `--fixer-cmd`. Rejected because issue #30 is specifically about runtime `agent next` requests.
- Submit directly from the helper. Rejected because helper direct mutation would blur adapter and runtime ownership.

## Decision: Keep classification and resolution distinct in wording and reason guidance

**Rationale**: Classification is triage evidence recorded before a mutating lease. Resolution is the fixer/verifier response decision. Using precise next-action text reduces retries without weakening the state machine.

**Alternatives considered**:

- Allow fixer requests to infer classification from resolution. Rejected because it bypasses the evidence-first triage gate.
- Rename protocol fields. Rejected because it would be a breaking public contract change.

## Decision: Treat `submit-batch` as the low-overhead path, not a lease bypass

**Rationale**: Existing runtime behavior already supports shared evidence for multiple GitHub-thread fixes. The correct repair is guidance and tests that make this path discoverable while preserving active lease requirements and all-or-nothing rejection.

**Alternatives considered**:

- Raise `max_parallel_claims` above 2. Rejected for this issue because the safety tradeoff needs a broader scheduling policy decision.
- Add batch support for local findings. Rejected because local finding handling can require different response and closure semantics.
