from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class JsonIOError(RuntimeError):
    def __init__(self, reason_code: str, detail: str):
        self.reason_code = reason_code
        super().__init__(detail)


def write_json_atomic(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(_json_ready(payload), handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, target)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def read_json_object(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise JsonIOError("JSON_FILE_NOT_FOUND", f"JSON file does not exist: {target}") from exc
    except json.JSONDecodeError as exc:
        raise JsonIOError("INVALID_JSON", f"Invalid JSON at {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise JsonIOError("INVALID_JSON_OBJECT", f"JSON file must contain an object: {target}")
    return payload


def _json_ready(value: Any) -> Any:
    # Fast path: check exact types to avoid expensive `is_dataclass` overhead and
    # slower `isinstance` evaluations during heavy recursion.
    _type = type(value)
    if _type is str or _type is int or _type is float or _type is bool or value is None:
        return value
    if _type is dict:
        return {str(key): _json_ready(inner) for key, inner in value.items()}
    if _type is list:
        return [_json_ready(inner) for inner in value]

    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(inner) for inner in value]
    return value
