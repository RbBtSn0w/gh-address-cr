from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gh_address_cr.agent.roles import AgentRole, parse_role
from gh_address_cr.core.models import CapabilityManifest


class ManifestValidationError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


REQUIRED_MANIFEST_FIELDS = (
    "agent_id",
    "roles",
    "actions",
    "input_formats",
    "output_formats",
    "protocol_versions",
)


def _require_non_empty_list(payload: dict[str, Any], field: str) -> None:
    if field not in payload:
        raise ManifestValidationError(f"missing_{field}", f"CapabilityManifest missing {field}.")
    value = payload[field]
    if not isinstance(value, list) or not value:
        raise ManifestValidationError(f"invalid_{field}", f"CapabilityManifest field {field} must be a non-empty list.")


def validate_capability_manifest(payload: CapabilityManifest | dict[str, Any]) -> CapabilityManifest:
    if isinstance(payload, CapabilityManifest):
        payload = payload.to_dict()
    if not isinstance(payload, dict):
        raise ManifestValidationError("invalid_manifest", "CapabilityManifest must be a JSON object.")
    for field in REQUIRED_MANIFEST_FIELDS:
        if field == "agent_id":
            if not payload.get(field):
                raise ManifestValidationError(f"missing_{field}", f"CapabilityManifest missing {field}.")
            continue
        _require_non_empty_list(payload, field)
    try:
        manifest = CapabilityManifest.from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ManifestValidationError("malformed_manifest", str(exc)) from exc
    max_claims = manifest.constraints.get("max_parallel_claims")
    if max_claims is not None and (not isinstance(max_claims, int) or max_claims < 1):
        raise ManifestValidationError(
            "invalid_max_parallel_claims",
            "constraints.max_parallel_claims must be a positive integer when provided.",
        )
    return manifest


def load_capability_manifest(path: str | Path) -> CapabilityManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_capability_manifest(payload)


def is_manifest_eligible(
    manifest: CapabilityManifest | dict[str, Any],
    role: AgentRole | str,
    action: str,
    input_format: str,
    protocol_version: str,
    active_claims: int = 0,
    output_format: str = "action_response.v1",
) -> bool:
    try:
        ensure_manifest_eligible(
            manifest,
            role,
            action,
            input_format,
            protocol_version,
            active_claims,
            output_format,
        )
    except ManifestValidationError:
        return False
    return True


def ensure_manifest_eligible(
    manifest: CapabilityManifest | dict[str, Any],
    role: AgentRole | str,
    action: str,
    input_format: str,
    protocol_version: str,
    active_claims: int = 0,
    output_format: str = "action_response.v1",
) -> CapabilityManifest:
    manifest = validate_capability_manifest(manifest)
    parsed_role = parse_role(role)
    if parsed_role not in manifest.roles:
        raise ManifestValidationError("manifest_role_not_declared", f"Role {parsed_role.value} is not declared.")
    if action not in manifest.actions:
        raise ManifestValidationError("manifest_action_not_declared", f"Action {action} is not declared.")
    if input_format not in manifest.input_formats:
        raise ManifestValidationError("manifest_input_format_not_declared", f"Input format {input_format} is not declared.")
    if output_format not in manifest.output_formats:
        raise ManifestValidationError(
            "manifest_output_format_not_declared",
            f"Output format {output_format} is not declared.",
        )
    if protocol_version not in manifest.protocol_versions:
        raise ManifestValidationError(
            "manifest_protocol_version_not_declared",
            f"Protocol version {protocol_version} is not declared.",
        )
    max_claims = manifest.constraints.get("max_parallel_claims")
    if max_claims is not None and active_claims >= max_claims:
        raise ManifestValidationError("manifest_max_parallel_claims_exceeded", "Agent has no remaining claim capacity.")
    return manifest
