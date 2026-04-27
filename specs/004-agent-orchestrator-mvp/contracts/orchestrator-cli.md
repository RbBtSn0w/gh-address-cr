# Orchestrator CLI Contract

The MVP Orchestrator adds the following commands under the `agent orchestrate` group:

- `gh-address-cr agent orchestrate start <owner/repo> <pr_number>`: Initializes the orchestration session and generates the initial work queue.
- `gh-address-cr agent orchestrate step <owner/repo> <pr_number> [--role <role>]`: Polls the runtime status, generates the next `WorkerPacket`, and outputs it.
- `gh-address-cr agent orchestrate resume <owner/repo> <pr_number>`: Reloads `orchestration.json`, validates active leases, and continues execution.
- `gh-address-cr agent orchestrate status <owner/repo> <pr_number>`: Prints the current queue and active leases.
- `gh-address-cr agent orchestrate stop <owner/repo> <pr_number>`: Gracefully pauses coordination and flushes state.

## Command Conventions
All commands MUST accept standard `<owner/repo> <pr_number>` arguments and support `--human` and `--machine` output flags consistent with the main `gh-address-cr` CLI.

## State Transitions
The orchestration state tracks volatile coordination progress:
- **INITIALIZED**: Triggered by `start`. Ready to generate packets.
- **RUNNING**: Triggered during `step` execution when issuing a packet or submitting a response.
- **PAUSED**: Triggered by `stop` or after `step` successfully finishes processing one item.
- **COMPLETED**: Reached when `status` shows zero pending items, zero active leases, and final-gate passes.
- **FAILED**: Reached when `resume`, `step`, or `submit` encounters corruption, lease conflicts, or validation errors.