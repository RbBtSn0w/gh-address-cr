# Quickstart: Integrated Orchestrator

## 1. Initialize Orchestration
```bash
python3 -m gh_address_cr agent orchestrate start owner/repo 123
```
This loads the current session from `session.json` and prepares the initial work queue.

```bash
python3 -m gh_address_cr agent orchestrate status owner/repo 123
```
Use this to verify the authoritative queue size before dispatch.

## 2. Dispatch a Task
```bash
python3 -m gh_address_cr agent orchestrate step owner/repo 123 > packet.json
```
The orchestrator calls `workflow.issue_action_request`, creates a lease, and outputs the `WorkerPacket`.

## 3. Submit Response
```bash
python3 -m gh_address_cr agent orchestrate submit owner/repo 123 \
  --item-id "local-finding:abc" \
  --token "lease-xyz" \
  --input "response.json"
```
The orchestrator verifies the evidence in `response.json`, then calls `workflow.submit_action_response` to update the core session.

## 4. Final Gate Check
```bash
python3 -m gh_address_cr agent orchestrate stop owner/repo 123
```
If the PR is complete and all threads are resolved, it returns exit code 0. If unresolved items exist, it fails with code 2.

## 5. Re-sync After External Changes
```bash
python3 -m gh_address_cr agent orchestrate resume owner/repo 123
python3 -m gh_address_cr agent orchestrate status owner/repo 123
```
`resume` re-synchronizes orchestration state from runtime truth, including queue consistency.
