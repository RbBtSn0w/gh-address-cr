from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from gh_address_cr.core.telemetry_models import SAFE_STATUSES, ExternalTelemetryEvent, TelemetryParseResult
from gh_address_cr.core.telemetry_safety import _json_loads_strict


class TelemetryAdapter(ABC):
    @abstractmethod
    def parse(self, raw: str, source: str) -> TelemetryParseResult:
        """Parse raw telemetry into a TelemetryParseResult.

        Expected producer/input failures must be represented by a rejected
        TelemetryParseResult or by raising ValueError/TypeError. Adapter
        implementations should validate payload shape before indexing so
        malformed input does not leak KeyError or IndexError; those exception
        types are treated as adapter bugs and fail loud at the import boundary.
        """


class TelemetryAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str | None], TelemetryAdapter] = {}

    def register(self, fmt: str, adapter: TelemetryAdapter, source: str | None = None) -> None:
        key = (fmt, source)
        if key in self._adapters:
            raise ValueError(f"Adapter for format '{fmt}' and source '{source}' is already registered.")
        self._adapters[key] = adapter

    def get_adapter(self, fmt: str, source: str | None = None) -> TelemetryAdapter | None:
        if source is not None:
            adapter = self._adapters.get((fmt, source))
            if adapter is not None:
                return adapter
        return self._adapters.get((fmt, None))

    def unregister(self, fmt: str, source: str | None = None) -> None:
        self._adapters.pop((fmt, source), None)


_registry = TelemetryAdapterRegistry()


def register_adapter(fmt: str, adapter: TelemetryAdapter, source: str | None = None) -> None:
    _registry.register(fmt, adapter, source)


def get_adapter(fmt: str, source: str | None = None) -> TelemetryAdapter | None:
    return _registry.get_adapter(fmt, source)


def unregister_adapter(fmt: str, source: str | None = None) -> None:
    _registry.unregister(fmt, source)


class GenericAgentJsonlAdapter(TelemetryAdapter):
    def __init__(
        self,
        *,
        normalize_external_event: Callable[[object, str], ExternalTelemetryEvent],
    ) -> None:
        self._normalize_external_event = normalize_external_event

    def parse(self, raw: str, source: str) -> TelemetryParseResult:
        accepted: list[ExternalTelemetryEvent] = []
        diagnostics: list[str] = []
        rejected_count = 0
        unsafe_seen = False
        malformed_seen = False

        for line_number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = _json_loads_strict(line)
            except json.JSONDecodeError as exc:
                malformed_seen = True
                rejected_count += 1
                diagnostics.append(f"line {line_number}: invalid JSON: {exc.msg}")
                continue
            except ValueError as exc:
                malformed_seen = True
                rejected_count += 1
                diagnostics.append(f"line {line_number}: invalid JSON: {exc}")
                continue
            try:
                event = self._normalize_external_event(payload, source)
            except ValueError as exc:
                message = str(exc)
                if message.startswith("UNSAFE:"):
                    unsafe_seen = True
                    diagnostics.append(f"line {line_number}: {message.removeprefix('UNSAFE:')}")
                else:
                    malformed_seen = True
                    diagnostics.append(f"line {line_number}: {message}")
                rejected_count += 1
                continue
            accepted.append(event)

        return TelemetryParseResult(
            events=accepted,
            rejected_count=rejected_count,
            unsafe_seen=unsafe_seen,
            malformed_seen=malformed_seen,
            diagnostics=diagnostics,
            events_are_normalized=True,
        )


class CodexHostJsonAdapter(TelemetryAdapter):
    def parse(self, raw: str, source: str) -> TelemetryParseResult:
        try:
            payload = _json_loads_strict(raw)
        except json.JSONDecodeError as exc:
            return TelemetryParseResult([], 1, False, True, [f"invalid JSON: {exc.msg}"])
        except ValueError as exc:
            return TelemetryParseResult([], 1, False, True, [f"invalid JSON: {exc}"])
        if not isinstance(payload, dict):
            return TelemetryParseResult([], 1, False, True, ["codex host payload must be an object"])

        session_id = str(payload.get("session_id") or payload.get("thread_id") or "")
        if not session_id:
            return TelemetryParseResult([], 1, False, True, ["codex host payload missing session_id"])
        turns = payload.get("turns")
        if not isinstance(turns, list):
            return TelemetryParseResult([], 1, False, True, ["codex host payload turns must be a list"])

        events: list[ExternalTelemetryEvent] = []
        diagnostics: list[str] = []
        rejected = 0
        for index, turn in enumerate(turns):
            if not isinstance(turn, dict):
                rejected += 1
                diagnostics.append(f"turn {index}: turn must be an object")
                continue
            event_id = str(turn.get("id") or turn.get("turn_id") or f"turn-{index}")
            duration_ms = _coerce_duration_ms(_first_present(turn, "duration_ms", "duration"))
            if duration_ms is None:
                rejected += 1
                diagnostics.append(f"turn {index}: missing duration_ms")
                continue
            metadata = _codex_turn_metadata(turn)
            events.append(
                ExternalTelemetryEvent(
                    schema_version="telemetry.external.v1",
                    source=source,
                    source_session_id=session_id,
                    event_id=event_id,
                    kind="agent_step",
                    operation=str(turn.get("operation") or "codex.turn"),
                    status=_normalize_host_status(turn.get("status")),
                    duration_ms=duration_ms,
                    started_at=_optional_str(turn.get("started_at")),
                    ended_at=_optional_str(turn.get("ended_at")),
                    metadata=metadata,
                    correlation_id=_optional_str(turn.get("correlation_id")),
                )
            )
            tool_calls = turn.get("tool_calls") or []
            if isinstance(tool_calls, list):
                for tool_index, tool in enumerate(tool_calls):
                    if not isinstance(tool, dict):
                        continue
                    tool_duration = _coerce_duration_ms(_first_present(tool, "duration_ms", "duration")) or 0
                    events.append(
                        ExternalTelemetryEvent(
                            schema_version="telemetry.external.v1",
                            source=source,
                            source_session_id=session_id,
                            event_id=f"{event_id}:tool-{tool_index}",
                            kind="tool_call",
                            operation=str(tool.get("name") or tool.get("operation") or "tool_call"),
                            status=_normalize_host_status(tool.get("status")),
                            duration_ms=tool_duration,
                            started_at=_optional_str(tool.get("started_at")),
                            ended_at=_optional_str(tool.get("ended_at")),
                            metadata={},
                            correlation_id=event_id,
                        )
                    )
        return TelemetryParseResult(events, rejected, False, bool(rejected), diagnostics)


def _first_present(payload: dict[str, Any], *keys: str) -> Any | None:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _codex_turn_metadata(turn: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    tokens = turn.get("tokens")
    if isinstance(tokens, dict):
        for source_key, target_key in (
            ("input", "token_input_count"),
            ("output", "token_output_count"),
            ("total", "token_total_count"),
        ):
            value = _coerce_positive_count(tokens.get(source_key))
            if value is not None:
                metadata[target_key] = value
    tool_calls = turn.get("tool_calls")
    if isinstance(tool_calls, list):
        metadata["tool_call_count"] = len(tool_calls)
    return metadata


def _coerce_duration_ms(value: Any) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return int(number)


def _coerce_positive_count(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _normalize_host_status(value: Any) -> str:
    status = str(value or "unknown").lower()
    return status if status in SAFE_STATUSES else "unknown"


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
