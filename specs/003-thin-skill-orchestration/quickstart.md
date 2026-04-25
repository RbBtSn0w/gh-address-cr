# Quickstart: Thin Skill Orchestration

## Goal

Validate the next-stage contract manually without introducing a custom autonomous runner. The dry run uses the high-level runtime interface, role boundaries, leases, structured evidence, and final gate.

## Prerequisites

From repository root:

```bash
python3 gh-address-cr/scripts/cli.py --help
python3 gh-address-cr/scripts/cli.py adapter check-runtime
```

Expected result:

- The CLI is available.
- The packaged skill shim delegates to the runtime or fails loudly before mutation.
- Operators use high-level public commands rather than low-level implementation scripts.

## Manual Orchestration Dry Run

### 1. Coordinator Starts Or Resumes A PR Session

```bash
python3 gh-address-cr/scripts/cli.py review <owner/repo> <pr_number>
```

Expected behavior:

- If findings are absent, the runtime returns a structured waiting state for external review.
- If work is available, the runtime emits structured status and artifact paths.
- The operator reads machine fields, not human prose.

### 2. Review Producer Provides Findings

Accepted producer output:

- Normalized findings JSON.
- Fixed `finding` blocks converted through the documented converter.

Rejected producer output:

- Narrative-only Markdown.
- Mixed prose that lacks fixed `finding` blocks.

Continue with:

```bash
python3 gh-address-cr/scripts/cli.py review <owner/repo> <pr_number>
```

Expected behavior:

- Producer identity does not change downstream session handling.
- Invalid producer output fails loudly with actionable guidance.

### 3. Coordinator Assigns Work By Role

Use the runtime agent protocol for multi-agent work:

```bash
gh-address-cr agent manifest
gh-address-cr agent next <owner/repo> <pr_number> --role triage --agent-id triage-1
gh-address-cr agent next <owner/repo> <pr_number> --role fixer --agent-id fixer-1
gh-address-cr agent next <owner/repo> <pr_number> --role verifier --agent-id verifier-1
```

Expected behavior:

- Each mutating item receives a bounded claim lease.
- Capability and role compatibility are checked before work assignment.
- Conflicting item, file, thread, or side-effect ownership is rejected or serialized.

### 4. Agents Submit Structured Evidence

Each role submits through the runtime:

```bash
gh-address-cr agent submit <owner/repo> <pr_number> --input response.json
```

Expected behavior:

- The runtime accepts only the active lease holder's response.
- Stale, duplicate, malformed, cross-role, or missing-evidence responses are rejected and recorded.
- Fix responses include changed-file and validation evidence.
- Clarify, defer, and reject responses include reply or rationale evidence.

### 5. Verifier Handles Rejection Safely

When verifier evidence rejects a fixer response:

- The item returns to a blocked state.
- No GitHub reply or resolve side effect is published.
- The next runtime status gives an actionable recovery path.

### 6. Runtime Publishes Side Effects

After accepted evidence is ready:

```bash
python3 gh-address-cr/scripts/cli.py review <owner/repo> <pr_number>
```

Expected behavior:

- GitHub replies and resolves are serialized through the runtime.
- AI agents do not call GitHub side-effect commands directly.
- Reply evidence and resolve state are recorded before completion.

### 7. Gatekeeper Proves Completion

```bash
python3 gh-address-cr/scripts/cli.py final-gate <owner/repo> <pr_number>
```

Expected behavior:

- Completion is claimable only after final gate passes.
- Final gate checks unresolved remote threads, current-login pending reviews, terminal reply evidence, blocking local items, and validation evidence.

## Documentation And Contract Validation

Run the planned local checks:

```bash
ruff check gh-address-cr tests
python3 -m unittest discover -s tests
python3 gh-address-cr/scripts/cli.py --help
```

Expected additional test coverage for this feature:

- Status-to-action mapping fixtures.
- Packaged skill path-scope validation.
- Low-level script exposure validation.
- Producer intake rejection for narrative-only review output.
- Multi-agent lease conflict and verifier rejection scenarios.
- Final-gate-backed completion examples.

## Out Of Scope For This Stage

- Building a generic agent task runner.
- Adding a built-in review engine.
- Replacing normalized findings with narrative review prose.
- Making low-level scripts the recommended agent-safe public API.
- Allowing completion claims without final-gate evidence.
