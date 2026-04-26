# Orchestrator CLI Contract

The MVP Orchestrator adds the following commands under the `agent orchestrate` group:

- `gh-address-cr agent orchestrate start <owner/repo> <pr_number>`: Initializes the orchestration session and generates the initial work queue.
- `gh-address-cr agent orchestrate step <owner/repo> <pr_number> [--role <role>]`: Polls the runtime status, generates the next `WorkerPacket`, and outputs it.
- `gh-address-cr agent orchestrate resume <owner/repo> <pr_number>`: Reloads `orchestration.json`, validates active leases, and continues execution.
- `gh-address-cr agent orchestrate status <owner/repo> <pr_number>`: Prints the current queue and active leases.
- `gh-address-cr agent orchestrate stop <owner/repo> <pr_number>`: Gracefully pauses coordination and flushes state.