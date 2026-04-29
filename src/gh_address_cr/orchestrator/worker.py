import json
import os
from uuid import uuid4
from typing import Any, Dict, List

MAX_RETRIES = 3


class WorkerPacketValidationError(Exception):
    pass


class HumanHandoffRequired(Exception):
    pass


def parse_and_validate_response(
    response_path: str, required_evidence: List[str], retry_count: int = 0
) -> Dict[str, Any]:
    if not os.path.exists(response_path):
        raise WorkerPacketValidationError(f"Response path '{response_path}' does not exist.")

    try:
        with open(response_path, "r", encoding="utf-8") as f:
            content = f.read()
            if not content.strip():
                raise WorkerPacketValidationError(f"Response path '{response_path}' is empty.")
            response = json.loads(content)
    except json.JSONDecodeError as e:
        if retry_count >= MAX_RETRIES:
            raise HumanHandoffRequired(f"Max retries ({MAX_RETRIES}) reached. Failed to parse JSON: {e}")
        raise WorkerPacketValidationError(f"Failed to parse JSON response: {e}")

    validate_action_response(response, required_evidence)
    return response


def build_worker_packet(
    run_id: str,
    lease_token: str,
    role: str,
    session_id: str,
    item: Dict[str, Any],
    response_path: str,
    action_request: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    request_payload = action_request or {
        "request_id": f"req-{uuid4().hex}",
        "session_id": session_id,
        "lease_id": lease_token,
        "agent_role": role,
        "item": item,
        "allowed_actions": ["fix", "clarify", "defer"],
        "required_evidence": ["files", "validation_commands", "note", "fix_reply"],
    }
    return {
        "orchestration_run_id": run_id,
        "lease_token": lease_token,
        "role_requested": role,
        "action_request": request_payload,
        "relevant_file_context": f"{item.get('path', 'unknown')}:{item.get('line', '0')}",
        "submit_recovery_instruction": "Run validation commands to verify your fix. Write the response JSON strictly to the response_path.",
        "response_path": response_path,
    }


def validate_action_response(response: Dict[str, Any], required_evidence: List[str]) -> None:
    evidence = response.get("evidence") if isinstance(response.get("evidence"), dict) else response
    if not isinstance(evidence, dict):
        raise WorkerPacketValidationError("ActionResponse evidence payload must be a dictionary.")

    for req in required_evidence:
        if req not in evidence:
            raise WorkerPacketValidationError(f"ActionResponse evidence missing required field: '{req}'.")
