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
            json.dump(json_ready(payload), handle, indent=2, sort_keys=True)
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


def json_ready(value: Any) -> Any:
    """Normalize a value into JSON-serializable form.

    This is the single normalizer for the whole package; `core.utils.json_ready`
    re-exports it. It lives here because `core.io` imports nothing from the
    package, while `core.utils` reaches `core.io` through `core.session` — so
    the dependency can only point this way.

    Ordering matters: dataclass instances also carry `__dict__`, so the
    dataclass branch must run before the `__dict__` branch, or dataclasses
    would bypass `asdict` and lose its recursive field expansion.
    """
    # Performance optimized: exact type checks are significantly faster than isinstance/is_dataclass
    if value is None:
        return None
    t = type(value)
    if t is str or t is int or t is bool or t is float:
        return value
    if t is dict:
        return {str(key): json_ready(inner) for key, inner in value.items()}
    if t is list or t is tuple or t is set:
        return [json_ready(inner) for inner in value]

    # Fallback to isinstance for subclasses
    if isinstance(value, dict):
        return {str(key): json_ready(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_ready(inner) for inner in value]

    # Subclasses of JSON scalars are already serializable and must be returned
    # as-is. This notably covers `str`-based Enums such as `AgentRole`: sending
    # one through the `__dict__` branch below would emit enum internals, and
    # its `__objclass__` back-reference would then drag in an unserializable
    # `mappingproxy`.
    if isinstance(value, (str, int, float, bool)):
        return value

    if is_dataclass(value) and not isinstance(value, type):
        return json_ready(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    # Only instances are expanded. A class object also carries a `__dict__`,
    # but expanding one is never meaningful, so let the encoder fail loudly.
    if not isinstance(value, type) and hasattr(value, "__dict__"):
        return json_ready(vars(value))
    return value
