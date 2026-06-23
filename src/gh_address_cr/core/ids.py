from __future__ import annotations

import hashlib
import json
from typing import Any

from gh_address_cr.core.utils import json_ready


def stable_id(prefix: str, payload: dict[str, Any]) -> str:
    return f"{prefix}_{stable_payload_hash(payload)[:20]}"


def stable_payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(json_ready(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
