"""Strict machine-output assertions shared by installed CLI smoke tests."""

import json


def assert_machine_result(result, *, exit_code, status, reason_code):
    if result.returncode != exit_code:
        raise AssertionError(f"Expected exit {exit_code}, got {result.returncode}: {result.stdout}\n{result.stderr}")
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise AssertionError(f"Expected one complete JSON object: {result.stdout}\n{result.stderr}") from exc
    if not isinstance(payload, dict):
        raise AssertionError(f"Expected a JSON object, got {payload!r}")
    if payload.get("status") != status or payload.get("reason_code") != reason_code:
        raise AssertionError(f"Expected {status}/{reason_code}, got {payload!r}")
    return payload
