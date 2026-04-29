# Quickstart: Agent Control Plane

This quickstart describes the intended validation flow for the multi-agent
control-plane design. Some protocol commands are planned advanced/internal
commands and will become executable during implementation.

## Agent Ownership Lanes

- Runtime CLI Agent: `src/gh_address_cr/cli.py`, `src/gh_address_cr/core/session.py`, `src/gh_address_cr/core/workflow.py`, runtime command wiring
- Protocol Agent: `src/gh_address_cr/agent/`, `src/gh_address_cr/core/models.py`, protocol fixtures
- Lease Coordinator Agent: `src/gh_address_cr/core/leases.py`, lease lifecycle and conflict-key rules
- GitHub Evidence Agent: `src/gh_address_cr/github/`, `src/gh_address_cr/evidence/`, `src/gh_address_cr/intake/`
- Gate Agent: `src/gh_address_cr/core/gate.py`
- Skill Adapter Agent: `gh-address-cr/SKILL.md`, `gh-address-cr/scripts/cli.py`, `gh-address-cr/agents/`, `gh-address-cr/references/`
- Verification Agent: `tests/`, this quickstart, and final validation evidence

## 1. Run Existing Baseline Checks

```bash
python3 -m unittest discover -s tests
python3 gh-address-cr/scripts/cli.py --help
python3 gh-address-cr/scripts/cli.py cr-loop --help
```

## 2. Validate Runtime Installation

The target runtime entrypoint is:

```bash
python3 -m pip install -e .
gh-address-cr --help
python3 -m gh_address_cr --help
```

During migration, the skill-local shim remains available:

```bash
python3 gh-address-cr/scripts/cli.py --help
```

The shim must delegate to the installed runtime or fail loudly with remediation.

## 3. Start A Normal PR Session

The public entrypoint remains:

```bash
gh-address-cr review owner/repo 123
```

If the workflow returns `WAITING_FOR_EXTERNAL_REVIEW`, fill the handoff file
with findings JSON or fixed `finding` blocks, then rerun the same command.

## 4. Issue A Multi-Agent Action Request

Planned advanced/internal command:

```bash
gh-address-cr agent next owner/repo 123 --role fixer
```

Expected behavior:

- the CLI selects one eligible item
- the CLI creates one active `ClaimLease`
- the CLI writes an `ActionRequest`
- the AI fixer receives only the item, allowed actions, required evidence, and
  forbidden actions

Executable example with explicit agent id:

```bash
gh-address-cr agent next owner/repo 123 --role fixer --agent-id codex-fixer-1
```

## 5. Submit Agent Evidence

Planned advanced/internal command:

```bash
gh-address-cr agent submit owner/repo 123 --input action-response.json
```

Expected behavior:

- malformed JSON fails loudly
- stale or mismatched leases fail loudly
- missing evidence fails loudly
- accepted evidence is appended to the ledger
- GitHub side effects are still performed by the deterministic control plane

Verifier rejection behavior:

- `VERIFICATION_REJECTED` returns the item to open/blocked state
- `verification_rejected` is appended to the ledger
- no GitHub side-effect attempt is emitted

## 6. Verify Parallel Coordination

Create at least three independent items and issue separate fixer leases.

Expected behavior:

- one active lease per item
- no duplicate accepted submissions for the same active lease
- stale leases can be reclaimed
- verifier rejection returns the item to blocked/open state without GitHub
  side effects

## 7. Publish And Gate

After evidence is accepted, rerun:

```bash
gh-address-cr review owner/repo 123
gh-address-cr final-gate owner/repo 123
```

Completion can be claimed only after `final-gate` proves:

- zero unresolved GitHub threads
- zero current-login pending reviews
- zero session blocking items
- no terminal GitHub thread missing durable reply evidence
- required validation evidence is present for terminal findings and accepted
  fixes

## 8. Validate Runtime / Skill Separation

Expected requirements before implementation proceeds:

- direct runtime invocation and skill shim invocation report compatible status
  contracts
- missing runtime fails before session mutation
- incompatible runtime fails before session mutation
- skill-owned docs describe the runtime as an external prerequisite
- no skill Markdown is the only owner of a state transition, GitHub side
  effect, or final-gate rule

## 9. Implementation Readiness Evidence

Fresh verification commands to run before claiming this implementation ready:

```bash
ruff check gh-address-cr src tests
python3 -m unittest discover -s tests
python3 gh-address-cr/scripts/cli.py --help
PYTHONPATH=src python3 -m gh_address_cr --help
python3 gh-address-cr/scripts/cli.py cr-loop --help
python3 gh-address-cr/scripts/cli.py final-gate --help
git diff --check
```

Focused coverage commands:

```bash
python3 -m unittest tests.test_runtime_packaging tests.test_skill_runtime_shim
python3 -m unittest tests.test_agent_protocol tests.test_findings_intake tests.test_control_plane_workflow
python3 -m unittest tests.test_claim_leases tests.test_evidence_ledger tests.test_final_gate
```

Current blocker categories:

- Runtime CLI Agent: no known blocker
- Protocol Agent: no known blocker
- Lease Coordinator Agent: no known blocker
- GitHub Evidence Agent: no known blocker
- Gate Agent: no known blocker
- Skill Adapter Agent: no known blocker
- Verification Agent: final evidence must be refreshed after any further edit

Latest verification snapshot:

- `ruff check gh-address-cr src tests` -> `All checks passed!`
- `python3 -m unittest discover -s tests` -> `Ran 306 tests in 99.602s OK`
- `python3 gh-address-cr/scripts/cli.py --help` -> exit `0`
- `PYTHONPATH=src python3 -m gh_address_cr --help` -> exit `0`
- `python3 gh-address-cr/scripts/cli.py adapter check-runtime` -> `status: compatible`
- `python3 gh-address-cr/scripts/cli.py cr-loop --help` -> exit `0`
- `python3 gh-address-cr/scripts/cli.py final-gate --help` -> exit `0`
- `git diff --check` -> exit `0`
