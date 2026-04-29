# Orchestrator MVP Data Model

## OrchestrationSession
- `run_id`: str
- `repo`: str
- `pr_number`: str
- `state`: str (INITIALIZED, RUNNING, PAUSED, COMPLETED, FAILED)
- `active_leases`: dict[str, LeaseRecord]
- `queued_items`: list[str]

## WorkerPacket
- `orchestration_run_id`: str
- `lease_token`: str
- `role_requested`: str
- `action_request`: ActionRequest (from existing schema)
- `response_path`: str (where the worker should write its response)

## LeaseRecord
- `item_id`: str
- `assigned_role`: str
- `agent_id`: str
- `lease_token`: str
- `expires_at`: datetime
