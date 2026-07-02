"""Telemetry content-safety helpers: redaction, sanitization, and validation.

Extracted from telemetry.py to give the redaction/sanitization concern a single
home. These are leaf functions (stdlib + the constants below only); the rest of
the telemetry module re-imports them so call sites stay unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from gh_address_cr.core.otel_semconv import (
    GEN_AI_AGENT_NAME,
    GEN_AI_CONVERSATION_ID,
    VCS_CHANGE_ID,
    VCS_CHANGE_STATE,
    VCS_PROVIDER_NAME,
    VCS_REPOSITORY_NAME,
)

# Commands that operate on a GitHub PR (`owner/repo <pr>`); only these carry vcs.*
_PR_SCOPED_COMMANDS = frozenset(
    {
        "active-pr",
        "address",
        "review",
        "threads",
        "findings",
        "adapter",
        "final-gate",
        "agent",
        "review-to-findings",
        "submit-action",
        "command-session",
    }
)

UNSAFE_METADATA_KEYS = {
    "token",
    "access_token",
    "authorization",
    "password",
    "secret",
    "credential",
    "raw_prompt",
    "prompt",
    "username",
    "user",
    "machine_id",
    "host_id",
}
UNSAFE_METADATA_KEY_MARKERS = (
    "token",
    "authorization",
    "password",
    "secret",
    "credential",
    "prompt",
)
TOKEN_MARKERS = ("ghp_", "github_pat_", "xoxb-", "token=")


def _safe_metadata(metadata: object) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    _validate_safe_metadata_value(metadata)
    result = {str(key): value for key, value in metadata.items()}
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"metadata contains non-JSON serializable or non-finite values: {exc}") from None
    return result


def _safe_diagnostic_text(value: str) -> str:
    if (
        _contains_control_character(value)
        or _contains_token_marker(value)
        or _contains_private_identifier(value)
        or _looks_like_unnecessary_absolute_path(value)
    ):
        return "[redacted]"
    return value


def _validate_safe_metadata_value(value: object, *, key_path: str = "metadata") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            if _is_unsafe_metadata_key(key_text):
                raise ValueError(f"UNSAFE:unsafe metadata field: {key_text}")
            if _contains_token_marker(key_text):
                raise ValueError(f"UNSAFE:unsafe token in metadata field key: {key_text}")
            if _contains_private_identifier(key_text):
                raise ValueError(f"UNSAFE:unsafe private identifier in metadata field key: {key_text}")
            if _looks_like_unnecessary_absolute_path(key_text):
                raise ValueError(f"UNSAFE:unsafe absolute path in metadata field key: {key_text}")
            if _contains_control_character(key_text):
                raise ValueError(f"UNSAFE:unsafe control character in metadata field key: {key_text}")
            _validate_safe_metadata_value(nested, key_path=f"{key_path}.{key_text}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_safe_metadata_value(item, key_path=f"{key_path}[{index}]")
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    value_text = value if isinstance(value, str) else str(value)
    if _contains_token_marker(value_text):
        raise ValueError(f"UNSAFE:unsafe metadata value at {key_path}")
    if _contains_private_identifier(value_text):
        raise ValueError(f"UNSAFE:unsafe private identifier in metadata value at {key_path}")
    if _looks_like_unnecessary_absolute_path(value_text):
        raise ValueError(f"UNSAFE:unsafe absolute path in metadata value at {key_path}")


def _safe_operation(operation: str) -> str:
    if _contains_control_character(operation):
        raise ValueError("UNSAFE:unsafe control character in operation label")
    if _contains_token_marker(operation):
        raise ValueError("UNSAFE:unsafe operation label")
    if _contains_private_identifier(operation):
        raise ValueError("UNSAFE:unsafe private identifier in operation label")
    if _looks_like_unnecessary_absolute_path(operation):
        raise ValueError("UNSAFE:unsafe absolute path in operation label")
    return operation


def _safe_source_label(source: str) -> str:
    if source == "runtime":
        raise ValueError("UNSAFE:reserved source label: runtime")
    if _contains_control_character(source):
        raise ValueError("UNSAFE:unsafe control character in source label")
    if _contains_token_marker(source):
        raise ValueError("UNSAFE:unsafe source label")
    if _contains_private_identifier(source):
        raise ValueError("UNSAFE:unsafe private identifier in source label")
    if _looks_like_unnecessary_absolute_path(source):
        raise ValueError("UNSAFE:unsafe absolute path in source label")
    return source


def _safe_source_session_id(source_session_id: str) -> str:
    if _contains_token_marker(source_session_id):
        raise ValueError("UNSAFE:unsafe source_session_id")
    if _contains_private_identifier(source_session_id):
        raise ValueError("UNSAFE:unsafe source_session_id")
    if _looks_like_unnecessary_absolute_path(source_session_id):
        raise ValueError("UNSAFE:unsafe absolute path in source_session_id")
    return source_session_id


def _safe_correlation_id(correlation_id: str) -> str:
    try:
        return _safe_source_session_id(correlation_id)
    except ValueError as exc:
        message = str(exc).replace("source_session_id", "correlation_id")
        raise ValueError(message) from None


def _safe_identity_label(value: str, *, field: str) -> str:
    if _contains_control_character(value):
        raise ValueError(f"UNSAFE:unsafe control character in {field}")
    if _contains_token_marker(value):
        raise ValueError(f"UNSAFE:unsafe {field}")
    if _contains_private_identifier(value):
        raise ValueError(f"UNSAFE:unsafe private identifier in {field}")
    if _looks_like_unnecessary_absolute_path(value):
        raise ValueError(f"UNSAFE:unsafe absolute path in {field}")
    return value


def _safe_optional_timestamp(value: object, *, field: str) -> str | None:
    if not value:
        return None
    text = str(value)
    if _contains_control_character(text):
        raise ValueError(f"UNSAFE:unsafe control character in {field}")
    if _contains_token_marker(text):
        raise ValueError(f"UNSAFE:unsafe {field}")
    if _contains_private_identifier(text):
        raise ValueError(f"UNSAFE:unsafe private identifier in {field}")
    if _looks_like_unnecessary_absolute_path(text):
        raise ValueError(f"UNSAFE:unsafe absolute path in {field}")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{field} must be an ISO timestamp") from None
    return text


def _safe_runtime_operation(operation: str) -> str:
    if (
        _contains_token_marker(operation)
        or _contains_private_identifier(operation)
        or _contains_control_character(operation)
        or _looks_like_unnecessary_absolute_path(operation)
    ):
        try:
            return command_label(shlex.split(operation)) or "runtime command"
        except ValueError:
            return "runtime command"
    return operation


_DRIVE_RE = re.compile(r"(^|\s)[a-zA-Z]:\\[^\s]+")


def _looks_like_unnecessary_absolute_path(value: str) -> bool:
    lowered = value.lower()
    if (
        "/users/" in lowered
        or "/private/" in lowered
        or "/home/" in lowered
        or "/root/" in lowered
        or "/workspace/" in lowered
        or "/tmp/" in lowered
        or "/var/" in lowered
        or "/opt/" in lowered
        or "/mnt/" in lowered
        or "/builds/" in lowered
        or "/runner/work/" in lowered
        or "c:\\users\\" in lowered
    ):
        return True
    if ":\\" in value:
        return bool(_DRIVE_RE.search(value))
    return False


_KEY_MARKER_PAIRS = [
    (marker, re.compile(rf"(^|[_-]){re.escape(marker)}($|[_-])"))
    for marker in UNSAFE_METADATA_KEY_MARKERS
]
_KEY_RE = re.compile(r"(^|[_-])key($|[_-])")


def _is_unsafe_metadata_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in {"token_input_count", "token_output_count", "token_total_count"}:
        return False
    if lowered in UNSAFE_METADATA_KEYS:
        return True

    for marker, pattern in _KEY_MARKER_PAIRS:
        if marker in lowered and pattern.search(lowered):
            return True

    if "key" in lowered:
        return bool(_KEY_RE.search(lowered))

    return False


_BEARER_RE = re.compile(r"(^|[^a-z0-9])bearer\s+")
_SK_RE = re.compile(r"(^|[^a-z0-9])sk-[a-z0-9]")


def _contains_token_marker(value: str) -> bool:
    lowered = value.lower()
    for marker in TOKEN_MARKERS:
        if marker in lowered:
            return True
    if "bearer" in lowered and _BEARER_RE.search(lowered):
        return True
    if "sk-" in lowered and _SK_RE.search(lowered):
        return True
    return False


def _contains_control_character(value: str) -> bool:
    return "\n" in value or "\r" in value or "\t" in value


_PRIVATE_IDENTIFIER_MARKERS = (
    "username",
    "user-id",
    "user_id",
    "machine-id",
    "machine_id",
    "machine-name",
    "machine_name",
    "host-id",
    "host_id",
    "host-name",
    "host_name",
)


def _contains_private_identifier(value: str) -> bool:
    lowered = value.lower()
    for marker in _PRIVATE_IDENTIFIER_MARKERS:
        if marker in lowered:
            return True
    return False


def _json_loads_strict(raw: str) -> Any:
    return json.loads(raw, parse_constant=_reject_json_constant)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def command_label(cmd: list[str]) -> str:
    """Return a public-safe command label for telemetry summaries."""
    cmd = _strip_inline_env_assignments(cmd)
    if not cmd:
        return ""

    label_tokens = [os.path.basename(cmd[0]) or cmd[0]]
    index = 1
    previous_was_flag = False
    if len(cmd) > 2 and label_tokens[0].startswith("python") and cmd[1] == "-m":
        label_tokens.extend(["-m", cmd[2]])
        index = 3
        previous_was_flag = False

    for token in cmd[index:]:
        if token == "--":
            break
        if token.startswith("-"):
            previous_was_flag = True
            continue
        if previous_was_flag:
            previous_was_flag = False
            continue
        if ":" in token:
            continue
        if "/" in token or "\\" in token or "=" in token:
            continue
        if _contains_token_marker(token):
            continue
        if _contains_private_identifier(token):
            continue
        label_tokens.append(token)
        break

    return shlex.join(label_tokens)


def _strip_inline_env_assignments(cmd: list[str]) -> list[str]:
    index = 0
    while index < len(cmd) and is_inline_env_assignment(cmd[index]):
        index += 1
    return cmd[index:]


def is_inline_env_assignment(token: str) -> bool:
    key, separator, _value = token.partition("=")
    return bool(separator and key and key.replace("_", "").isalnum() and not key[0].isdigit())


def split_inline_env_assignments(argv: list[str]) -> tuple[list[str], dict[str, str]]:
    index = 0
    inline_env: dict[str, str] = {}
    while index < len(argv) and is_inline_env_assignment(argv[index]):
        key, _separator, value = argv[index].partition("=")
        inline_env[key] = value
        index += 1
    return argv[index:], inline_env


def safe_command_args(argv: list[str]) -> list[str]:
    """Sanitize command line arguments to redact sensitive inputs for telemetry."""
    res = []
    for arg in argv:
        if "=" in arg:
            lhs, eq, rhs = arg.partition("=")
            key = lhs.lstrip("-")
            if (
                _is_unsafe_metadata_key(key)
                or _contains_token_marker(rhs)
                or _contains_private_identifier(rhs)
                or _looks_like_unnecessary_absolute_path(rhs)
            ):
                res.append(f"{lhs}=[redacted]")
            else:
                res.append(arg)
        else:
            if (
                _contains_token_marker(arg)
                or _contains_private_identifier(arg)
                or _looks_like_unnecessary_absolute_path(arg)
            ):
                res.append("[redacted]")
            else:
                res.append(arg)
    return res


def detect_agent_session(environ: Mapping[str, str]) -> dict[str, str]:
    """Detect and return agent session correlation attributes from environ.

    GH_ADDRESS_CR_CONVERSATION_ID is the designed, vendor-neutral entry point
    any agent can set (e.g. via skill guidance); CLAUDE_CODE_SESSION_ID is a
    passive, zero-configuration fallback used only because Claude Code exports
    it for free. This is intentionally bounded to these two sources, not a
    growing per-vendor detection registry (Principle X): a new agent vendor is
    onboarded by setting the designed entry point, not by adding a branch here.
    Precedence: GH_ADDRESS_CR_CONVERSATION_ID (explicit, designed) first, then
    CLAUDE_CODE_SESSION_ID (passive fallback).
    """
    res: dict[str, str] = {}

    # 1. Conversation ID (paired in one tuple so mypy narrows both together)
    conv_id_source: tuple[str, str] | None = None
    if "GH_ADDRESS_CR_CONVERSATION_ID" in environ:
        conv_id_source = (environ["GH_ADDRESS_CR_CONVERSATION_ID"], "GH_ADDRESS_CR_CONVERSATION_ID")
    elif "CLAUDE_CODE_SESSION_ID" in environ:
        conv_id_source = (environ["CLAUDE_CODE_SESSION_ID"], "CLAUDE_CODE_SESSION_ID")

    if conv_id_source is not None:
        conv_id, source = conv_id_source
        try:
            # Route through the public-safe path
            safe_conv_id = _safe_identity_label(conv_id, field=source)
            res[GEN_AI_CONVERSATION_ID] = safe_conv_id
            res["gen_ai.conversation.id.source"] = source
        except ValueError:
            pass

    # 2. Agent Name
    if "AI_AGENT" in environ:
        agent_name = environ["AI_AGENT"]
        try:
            safe_agent_name = _safe_identity_label(agent_name, field="AI_AGENT")
            res[GEN_AI_AGENT_NAME] = safe_agent_name
        except ValueError:
            pass

    return res


def derive_tool_name(argv: list[str] | None) -> str:
    """Derive the GenAI tool name from the command line arguments."""
    if not argv:
        return "gh-address-cr"
    first = argv[0]
    if first.startswith("-") or first in ("help", "version"):
        return "gh-address-cr"
    return first


def repo_hash(owner_repo: str) -> str:
    """Return a stable, one-way, case-insensitive digest of ``owner/repo``.

    Public-safe: the plain owner/repo name never appears in the output. Same
    repository (case-insensitively) always hashes identically; different
    repositories differ. Not used for security — only to group telemetry per
    repository without leaking private identifiers (spec FR-012 / R-010).
    """
    normalized = owner_repo.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def map_vcs_attributes(
    command: str,
    repo: str | None,
    pr_number: object | None,
    session: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Map a PR-scoped invocation to public-safe ``vcs.*`` span attributes.

    Returns ``{}`` unless ``command`` is PR-scoped and both ``repo`` and
    ``pr_number`` are present. Emits plain ``vcs.change.id`` (PR number) and
    ``vcs.provider.name=github``; ``vcs.repository.name`` is the one-way
    :func:`repo_hash` of ``owner/repo`` (never the plain name or URL).
    ``vcs.change.state`` is included only when the caller supplies it via
    ``session["status"]`` (no telemetry-driven GitHub lookup).
    """
    if command not in _PR_SCOPED_COMMANDS:
        return {}
    if not repo or pr_number is None:
        return {}

    attrs: dict[str, str] = {
        VCS_PROVIDER_NAME: "github",
        VCS_CHANGE_ID: str(pr_number),
        VCS_REPOSITORY_NAME: repo_hash(repo),
    }

    if session:
        state = session.get("status")
        if isinstance(state, str) and state:
            attrs[VCS_CHANGE_STATE] = state

    return attrs
