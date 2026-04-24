#!/usr/bin/env python3
from __future__ import annotations
import atexit
import gzip
import json
import os
import platform
import queue as queue_module
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import parse as urllib_parse
from urllib import request as urllib_request


SCRIPT_DIR = Path(__file__).resolve().parent
SESSION_ENGINE = SCRIPT_DIR / "session_engine.py"
_GITHUB_VIEWER_LOGIN: str | None = None
OTLP_HTTP_JSON_PROTOCOL = "http/json"
DEFAULT_OTLP_TIMEOUT_SECONDS = 3.0
DEFAULT_OTLP_COMPRESSION = "gzip"
DEFAULT_OTLP_SERVICE_NAME = "gh-address-cr-cli"
DEFAULT_PUBLIC_OTLP_RELAY_ENDPOINT = "https://gh-address-cr.hamiltonsnow.workers.dev"
OTLP_EXPORT_QUEUE_SIZE = 128
OTLP_EXPORT_FLUSH_GRACE_SECONDS = 0.2
POSIX_ABSOLUTE_PATH_RE = re.compile(r"(?P<prefix>^|[\s([{\"'<=,`])(?P<path>/[^\s`\"')\]}>;,]+)")
WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"(?P<prefix>^|[\s([{\"'<=,`])(?P<path>[A-Za-z]:\\[^\s`\"')\]}>;,]+)")
FILE_URI_RE = re.compile(r"(?P<prefix>^|[\s([{\"'<=,`])(?P<scheme>file://)(?P<path>/[^\s`\"')\]}>;,]+)")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
TOKEN_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}\b", re.IGNORECASE),
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b((?:[A-Za-z0-9]+[_-])*token|secret|password|api[_-]?key)\b([=: ]+)([^\s,;&]+)"
)

_OTLP_EXPORT_QUEUE: queue_module.Queue[dict] | None = None
_OTLP_EXPORT_THREAD: threading.Thread | None = None
_OTLP_EXPORT_LOCK = threading.Lock()
_OTLP_EXPORT_ATEXIT_REGISTERED = False


def state_dir() -> Path:
    override = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
    if override:
        path = Path(override)
        path.mkdir(parents=True, exist_ok=True)
        return path

    home = os.environ.get("HOME")
    if platform.system() == "Darwin":
        base = os.environ.get("XDG_CACHE_HOME") or (f"{home}/Library/Caches" if home else None)
    else:
        base = os.environ.get("XDG_CACHE_HOME") or (f"{home}/.cache" if home else None)
    if not base:
        raise SystemExit("Unable to determine a user cache directory. Set GH_ADDRESS_CR_STATE_DIR.")
    path = Path(base) / "gh-address-cr"
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_repo(repo: str) -> str:
    return repo.replace("/", "__")


def workspace_dir(repo: str, pr_number: str) -> Path:
    path = state_dir() / normalize_repo(repo) / f"pr-{pr_number}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def snapshot_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "threads.jsonl"


def previous_snapshot_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "threads.prev.jsonl"


def session_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "session.json"


def audit_log_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "audit.jsonl"


def trace_log_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "trace.jsonl"


def audit_summary_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "audit_summary.md"


def archive_root_dir(repo: str, pr_number: str) -> Path:
    path = state_dir() / "archive" / normalize_repo(repo) / f"pr-{pr_number}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def handled_threads_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "handled_threads.txt"


def findings_file(repo: str, pr_number: str, name: str = "code-review-findings.json") -> Path:
    return workspace_dir(repo, pr_number) / name


def producer_request_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "producer-request.md"


def incoming_findings_json_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "incoming-findings.json"


def incoming_findings_markdown_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "incoming-findings.md"


def normalized_handoff_findings_file(repo: str, pr_number: str) -> Path:
    return findings_file(repo, pr_number, "incoming-findings.normalized.json")


def last_machine_summary_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "last-machine-summary.json"


def reply_file(repo: str, pr_number: str, name: str) -> Path:
    return workspace_dir(repo, pr_number) / name


def loop_artifact_file(repo: str, pr_number: str, name: str) -> Path:
    return workspace_dir(repo, pr_number) / name


def validation_file(repo: str, pr_number: str, name: str) -> Path:
    return workspace_dir(repo, pr_number) / name


def github_pr_cache_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "github_pr_cache.json"


def load_session_payload(repo: str, pr_number: str) -> dict:
    path = session_file(repo, pr_number)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def item_has_reply_evidence(item: dict | None) -> bool:
    if not isinstance(item, dict):
        return False
    reply_url = item.get("reply_url")
    return bool(item.get("reply_posted")) and isinstance(reply_url, str) and bool(reply_url.strip())


def github_thread_reply_evidence(repo: str, pr_number: str, thread_id: str, *, require_tracked: bool = False) -> tuple[bool, str]:
    session = load_session_payload(repo, pr_number)
    items = session.get("items")
    if not isinstance(items, dict):
        return (False, f"GitHub thread {thread_id} is not tracked in session state.") if require_tracked else (True, "")
    item = items.get(f"github-thread:{thread_id}")
    if not isinstance(item, dict):
        return (False, f"GitHub thread {thread_id} is not tracked in session state.") if require_tracked else (True, "")
    if item_has_reply_evidence(item):
        return True, ""
    return False, f"GitHub thread {thread_id} is missing reply evidence; post a reply before resolving it."


class PullRequestReadCache:
    def __init__(self, repo: str, pr_number: str):
        self.repo = repo
        self.pr_number = pr_number
        self.path = github_pr_cache_file(repo, pr_number)
        self._payload = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._payload, sort_keys=True), encoding="utf-8")

    def head_sha(self) -> str | None:
        value = self._payload.get("head_sha")
        return value if isinstance(value, str) and value else None

    def set_head_sha(self, head_sha: str) -> None:
        self._payload["head_sha"] = head_sha
        files_by_head = self._payload.get("files_by_head")
        if not isinstance(files_by_head, dict):
            self._payload["files_by_head"] = {}
        self._save()

    def files_for_head(self, head_sha: str) -> list[dict] | None:
        files_by_head = self._payload.get("files_by_head")
        if not isinstance(files_by_head, dict):
            return None
        files = files_by_head.get(head_sha)
        return files if isinstance(files, list) else None

    def store_files_for_head(self, head_sha: str, files: list[dict]) -> None:
        self._payload["head_sha"] = head_sha
        self._payload["files_by_head"] = {head_sha: files}
        self._save()

    def get_or_load_files(self, head_sha: str, loader) -> list[dict]:
        cached = self.files_for_head(head_sha)
        if cached is not None:
            self._payload["head_sha"] = head_sha
            self._save()
            return cached
        files = loader()
        self.store_files_for_head(head_sha, files)
        return files


def encode_threads_snapshot(rows: list[dict]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def load_threads_snapshot_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def write_threads_snapshot(repo: str, pr_number: str, rows: list[dict]) -> Path:
    path = snapshot_file(repo, pr_number)
    path.write_text(encode_threads_snapshot(rows), encoding="utf-8")
    return path


def copy_threads_snapshot(repo: str, pr_number: str, source: Path) -> Path:
    target = snapshot_file(repo, pr_number)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def refresh_threads_snapshot(repo: str, pr_number: str) -> tuple[list[dict], Path]:
    rows = list_threads(repo, pr_number)
    return rows, write_threads_snapshot(repo, pr_number, rows)


def sha256_of_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_jsonl_event(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _is_windows_absolute_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value))


def _compact_absolute_path(value: str) -> str:
    if not value:
        return value
    if not (value.startswith("/") or _is_windows_absolute_path(value)):
        return value
    normalized = value.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if parts and re.match(r"^[A-Za-z]:$", parts[0]):
        parts = parts[1:]
    if len(parts) >= 2 and parts[0] in {"Users", "home"}:
        parts = parts[2:]
    elif len(parts) >= 3 and parts[:2] == ["var", "home"]:
        parts = parts[3:]
    elif len(parts) >= 4 and parts[0] == "mnt" and re.match(r"^[A-Za-z]$", parts[1]) and parts[2] in {"Users", "home"}:
        parts = parts[4:]
    elif len(parts) >= 5 and parts[0] == "mnt" and re.match(r"^[A-Za-z]$", parts[1]) and parts[2:4] == ["var", "home"]:
        parts = parts[5:]
    if not parts:
        return "..."
    return f".../{'/'.join(parts[-3:])}"


def _redact_telemetry_sensitive_text(value: str) -> str:
    redacted = EMAIL_RE.sub("[redacted-email]", value)
    for pattern in TOKEN_PATTERNS:
        redacted = pattern.sub("[redacted-token]", redacted)
    return SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[redacted-token]",
        redacted,
    )


def _sanitize_telemetry_string(value: str) -> str:
    sanitized = _redact_telemetry_sensitive_text(value)
    sanitized = FILE_URI_RE.sub(
        lambda match: f"{match.group('prefix')}{match.group('scheme')}{_compact_absolute_path(match.group('path'))}",
        sanitized,
    )
    sanitized = POSIX_ABSOLUTE_PATH_RE.sub(
        lambda match: f"{match.group('prefix')}{_compact_absolute_path(match.group('path'))}",
        sanitized,
    )
    sanitized = WINDOWS_ABSOLUTE_PATH_RE.sub(
        lambda match: f"{match.group('prefix')}{_compact_absolute_path(match.group('path'))}",
        sanitized,
    )
    return sanitized


def _sanitize_telemetry_value(value):
    if isinstance(value, str):
        return _sanitize_telemetry_string(value)
    if isinstance(value, dict):
        return {key: _sanitize_telemetry_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_telemetry_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_telemetry_value(item) for item in value]
    return value


def _parse_otlp_key_value_pairs(value: str) -> dict[str, str]:
    if not value.strip():
        return {}
    pairs: dict[str, str] = {}
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"Invalid OTLP key/value pair: {item}")
        key, raw_pair_value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("Invalid OTLP key/value pair: empty key")
        pairs[key] = urllib_parse.unquote(raw_pair_value.strip())
    return pairs


def _otlp_logs_protocol() -> str:
    protocol = (
        os.environ.get("OTEL_EXPORTER_OTLP_LOGS_PROTOCOL")
        or os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL")
        or OTLP_HTTP_JSON_PROTOCOL
    )
    if protocol != OTLP_HTTP_JSON_PROTOCOL:
        raise ValueError(f"Unsupported OTLP logs protocol: {protocol}. Only {OTLP_HTTP_JSON_PROTOCOL} is supported.")
    return protocol


def _normalize_otlp_logs_endpoint(value: str, *, signal_specific: bool) -> str:
    parsed = urllib_parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid OTLP logs endpoint: {value}")
    path = parsed.path or "/"
    if signal_specific:
        normalized_path = path or "/"
    elif path in {"", "/"}:
        normalized_path = "/v1/logs"
    else:
        normalized_path = f"{path.rstrip('/')}/v1/logs"
    return urllib_parse.urlunparse(parsed._replace(path=normalized_path, fragment=""))


def _otlp_logs_endpoint() -> str | None:
    logs_endpoint = (os.environ.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT") or "").strip()
    base_endpoint = (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
    if logs_endpoint:
        return _normalize_otlp_logs_endpoint(logs_endpoint, signal_specific=True)
    if base_endpoint:
        return _normalize_otlp_logs_endpoint(base_endpoint, signal_specific=False)
    return _normalize_otlp_logs_endpoint(DEFAULT_PUBLIC_OTLP_RELAY_ENDPOINT, signal_specific=False)


def _otlp_export_disabled() -> bool:
    value = (os.environ.get("GH_ADDRESS_CR_DISABLE_OTLP_EXPORT") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _otlp_logs_headers() -> dict[str, str]:
    raw_headers = os.environ.get("OTEL_EXPORTER_OTLP_LOGS_HEADERS")
    if raw_headers is None:
        raw_headers = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
    return _parse_otlp_key_value_pairs(raw_headers)


def _otlp_logs_timeout_seconds() -> float:
    raw_timeout = os.environ.get("OTEL_EXPORTER_OTLP_LOGS_TIMEOUT")
    if raw_timeout is None:
        raw_timeout = os.environ.get("OTEL_EXPORTER_OTLP_TIMEOUT", "")
    if not raw_timeout.strip():
        return DEFAULT_OTLP_TIMEOUT_SECONDS
    try:
        timeout_ms = int(raw_timeout)
    except ValueError as exc:
        raise ValueError(f"Invalid OTLP timeout: {raw_timeout}") from exc
    if timeout_ms <= 0:
        raise ValueError(f"Invalid OTLP timeout: {raw_timeout}")
    return timeout_ms / 1000.0


def _otlp_logs_compression() -> str:
    compression = (
        os.environ.get("OTEL_EXPORTER_OTLP_LOGS_COMPRESSION")
        or os.environ.get("OTEL_EXPORTER_OTLP_COMPRESSION")
        or DEFAULT_OTLP_COMPRESSION
    )
    if compression not in {"gzip", "none"}:
        raise ValueError(f"Unsupported OTLP logs compression: {compression}")
    return compression


def _otlp_resource_attributes() -> list[dict]:
    raw_attributes = os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "")
    resource_attributes = _parse_otlp_key_value_pairs(raw_attributes)
    service_name = (os.environ.get("OTEL_SERVICE_NAME") or "").strip()
    if service_name:
        resource_attributes["service.name"] = service_name
    else:
        resource_attributes.setdefault("service.name", DEFAULT_OTLP_SERVICE_NAME)
    return [{"key": key, "value": {"stringValue": value}} for key, value in sorted(resource_attributes.items())]


def _otlp_string_attribute(key: str, value: str | None) -> dict | None:
    if value is None or value == "":
        return None
    return {"key": key, "value": {"stringValue": value}}


def _otlp_severity_text(status: str) -> str:
    lowered = status.lower()
    if lowered in {"failed", "error", "rejected", "unknown"}:
        return "ERROR"
    if lowered in {"blocked", "waiting", "warn"}:
        return "WARN"
    return "INFO"


def _otlp_time_unix_nano(timestamp: str) -> str:
    return str(int(datetime.fromisoformat(timestamp).timestamp() * 1_000_000_000))


def _otlp_log_record(log_kind: str, entry: dict) -> dict:
    attributes = [
        _otlp_string_attribute("gh.address_cr.log_kind", log_kind),
        _otlp_string_attribute("gh.address_cr.action", str(entry.get("action") or "")),
        _otlp_string_attribute("gh.address_cr.status", str(entry.get("status") or "")),
        _otlp_string_attribute("gh.address_cr.repo", str(entry.get("repo") or "")),
        _otlp_string_attribute("gh.address_cr.pr", str(entry.get("pr") or "")),
        _otlp_string_attribute("gh.address_cr.run_id", str(entry.get("run_id") or "")),
        _otlp_string_attribute("gh.address_cr.audit_id", str(entry.get("audit_id") or "")),
    ]
    details = entry.get("details")
    if details:
        attributes.append(
            {
                "key": "gh.address_cr.details_json",
                "value": {"stringValue": json.dumps(details, sort_keys=True, separators=(",", ":"))},
            }
        )
    message = str(entry.get("message") or f"{entry.get('action', '')}:{entry.get('status', '')}")
    return {
        "timeUnixNano": _otlp_time_unix_nano(str(entry["timestamp"])),
        "observedTimeUnixNano": _otlp_time_unix_nano(str(entry["timestamp"])),
        "severityText": _otlp_severity_text(str(entry.get("status") or "")),
        "body": {"stringValue": message},
        "attributes": [attribute for attribute in attributes if attribute is not None],
    }


def _build_otlp_logs_payload(log_kind: str, entry: dict) -> dict:
    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": _otlp_resource_attributes(),
                },
                "scopeLogs": [
                    {
                        "scope": {
                            "name": "gh-address-cr",
                        },
                        "logRecords": [
                            _otlp_log_record(log_kind, entry),
                        ],
                    }
                ],
            }
        ]
    }


def _safe_otlp_endpoint(endpoint: str) -> str:
    parsed = urllib_parse.urlparse(endpoint)
    return urllib_parse.urlunparse(parsed._replace(query="", fragment=""))


def _sanitized_otlp_entry(entry: dict) -> dict:
    sanitized = dict(entry)
    sanitized["message"] = _sanitize_telemetry_string(str(entry.get("message") or ""))
    sanitized["details"] = _sanitize_telemetry_value(entry.get("details") or {})
    return sanitized


def _append_telemetry_export_failure(
    repo: str,
    pr_number: str,
    log_kind: str,
    entry: dict,
    endpoint: str | None,
    error: str,
    *,
    trace_path: Path | None = None,
) -> None:
    diagnostic = {
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "action": "telemetry_export",
        "status": "error",
        "repo": repo,
        "pr": pr_number,
        "run_id": entry.get("run_id"),
        "audit_id": entry.get("audit_id"),
        "message": f"OTLP log export failed for {log_kind}: {error}",
        "details": {
            "log_kind": log_kind,
            "source_action": entry.get("action"),
            "source_status": entry.get("status"),
            "endpoint": _safe_otlp_endpoint(endpoint) if endpoint else "",
        },
    }
    target_path = trace_path or trace_log_file(repo, pr_number)
    if trace_path is not None and not target_path.parent.exists():
        return
    try:
        append_jsonl_event(target_path, diagnostic)
    except OSError:
        return


def _build_otlp_export_request(log_kind: str, entry: dict) -> dict | None:
    endpoint = _otlp_logs_endpoint()
    if not endpoint:
        return None
    _otlp_logs_protocol()
    payload = json.dumps(
        _build_otlp_logs_payload(log_kind, _sanitized_otlp_entry(entry)),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "gh-address-cr/otel-http-json",
    }
    compression = _otlp_logs_compression()
    if compression == "gzip":
        payload = gzip.compress(payload)
        headers["Content-Encoding"] = "gzip"
    headers.update(_otlp_logs_headers())
    return {
        "log_kind": log_kind,
        "entry": entry,
        "endpoint": endpoint,
        "timeout": _otlp_logs_timeout_seconds(),
        "headers": headers,
        "payload": payload,
        "trace_path": trace_log_file(str(entry.get("repo") or ""), str(entry.get("pr") or "")),
    }


def _deliver_otlp_export(request_spec: dict) -> None:
    request = urllib_request.Request(
        request_spec["endpoint"],
        data=request_spec["payload"],
        headers=request_spec["headers"],
        method="POST",
    )
    with urllib_request.urlopen(request, timeout=request_spec["timeout"]) as response:
        response.read()


def _drain_otlp_export_queue_briefly() -> None:
    queue = _OTLP_EXPORT_QUEUE
    if queue is None:
        return
    deadline = time.monotonic() + OTLP_EXPORT_FLUSH_GRACE_SECONDS
    while queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.01)


def _otlp_export_worker() -> None:
    queue = _OTLP_EXPORT_QUEUE
    if queue is None:
        return
    while True:
        request_spec = queue.get()
        try:
            _deliver_otlp_export(request_spec)
        except Exception as exc:
            entry = request_spec["entry"]
            _append_telemetry_export_failure(
                str(entry.get("repo") or ""),
                str(entry.get("pr") or ""),
                str(request_spec["log_kind"] or ""),
                entry,
                request_spec.get("endpoint"),
                str(exc) or exc.__class__.__name__,
                trace_path=request_spec.get("trace_path"),
            )
        finally:
            queue.task_done()


def _ensure_otlp_export_worker() -> queue_module.Queue[dict]:
    global _OTLP_EXPORT_QUEUE
    global _OTLP_EXPORT_THREAD
    global _OTLP_EXPORT_ATEXIT_REGISTERED

    with _OTLP_EXPORT_LOCK:
        if _OTLP_EXPORT_QUEUE is None:
            _OTLP_EXPORT_QUEUE = queue_module.Queue(maxsize=OTLP_EXPORT_QUEUE_SIZE)
        if _OTLP_EXPORT_THREAD is None or not _OTLP_EXPORT_THREAD.is_alive():
            _OTLP_EXPORT_THREAD = threading.Thread(
                target=_otlp_export_worker,
                name="gh-address-cr-otlp-export",
                daemon=True,
            )
            _OTLP_EXPORT_THREAD.start()
        if not _OTLP_EXPORT_ATEXIT_REGISTERED:
            atexit.register(_drain_otlp_export_queue_briefly)
            _OTLP_EXPORT_ATEXIT_REGISTERED = True
        return _OTLP_EXPORT_QUEUE


def _export_otlp_log(log_kind: str, entry: dict) -> None:
    endpoint: str | None = None
    try:
        if _otlp_export_disabled():
            return
        request_spec = _build_otlp_export_request(log_kind, entry)
        if request_spec is None:
            return
        endpoint = request_spec["endpoint"]
        export_queue = _ensure_otlp_export_worker()
        export_queue.put_nowait(request_spec)
    except queue_module.Full:
        _append_telemetry_export_failure(
            str(entry.get("repo") or ""),
            str(entry.get("pr") or ""),
            log_kind,
            entry,
            endpoint,
            "telemetry export queue full",
        )
    except Exception as exc:
        _append_telemetry_export_failure(
            str(entry.get("repo") or ""),
            str(entry.get("pr") or ""),
            log_kind,
            entry,
            endpoint,
            str(exc) or exc.__class__.__name__,
        )


def trace_event(
    action: str,
    status: str,
    repo: str,
    pr_number: str,
    *,
    run_id: str | None = None,
    audit_id: str | None = None,
    message: str = "",
    details=None,
):
    entry = {
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "action": action,
        "status": status,
        "repo": repo,
        "pr": pr_number,
        "run_id": run_id,
        "audit_id": audit_id,
        "message": message,
        "details": details or {},
    }
    append_jsonl_event(trace_log_file(repo, pr_number), entry)
    _export_otlp_log("trace", entry)


def audit_event(
    action: str,
    status: str,
    repo: str,
    pr_number: str,
    audit_id: str | None = "default",
    message: str = "",
    details=None,
):
    entry = {
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "action": action,
        "status": status,
        "repo": repo,
        "pr": pr_number,
        "audit_id": audit_id,
        "run_id": audit_id,
        "message": message,
        "details": details or {},
    }
    append_jsonl_event(audit_log_file(repo, pr_number), entry)
    _export_otlp_log("audit", entry)
    trace_event(
        action,
        status,
        repo,
        pr_number,
        run_id=audit_id,
        audit_id=audit_id,
        message=message,
        details=details,
    )


def sanitize_run_id(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return sanitized or "run"


def reserve_archive_dir(repo: str, pr_number: str, run_id: str) -> Path:
    root = archive_root_dir(repo, pr_number)
    safe_run_id = sanitize_run_id(run_id)
    candidate = root / safe_run_id
    if not candidate.exists():
        return candidate
    suffix = 2
    while True:
        fallback = root / f"{safe_run_id}-{suffix}"
        if not fallback.exists():
            return fallback
        suffix += 1


def archive_workspace(repo: str, pr_number: str, run_id: str) -> Path:
    source = workspace_dir(repo, pr_number)
    if not source.exists():
        raise SystemExit(f"Workspace not found for archive: {source}")
    target = reserve_archive_dir(repo, pr_number, run_id)
    shutil.copytree(source, target)
    return target


TRANSIENT_GH_FAILURE_MARKERS = (
    "502",
    "503",
    "temporary failure",
    "timeout",
    "timed out",
    "connection reset",
    "graphql error",
    "graphql failed",
)


def is_transient_gh_failure(stderr: str | None = None, stdout: str | None = None, returncode: int | None = None) -> bool:
    _ = returncode
    text = f"{stderr or ''}\n{stdout or ''}".lower()
    return any(marker in text for marker in TRANSIENT_GH_FAILURE_MARKERS)


def run_cmd(cmd: list[str], *, input_text: str | None = None, check: bool = False, retries: int = 1) -> subprocess.CompletedProcess:
    attempts = max(1, retries)
    for attempt in range(attempts):
        try:
            result = subprocess.run(cmd, input=input_text, text=True, capture_output=True, check=check)
            if result.returncode != 0 and cmd and cmd[0] == "gh" and is_transient_gh_failure(result.stderr, result.stdout, result.returncode):
                if attempt < attempts - 1:
                    time.sleep(2**attempt)
                    continue
            return result
        except subprocess.CalledProcessError as exc:
            if cmd and cmd[0] == "gh" and attempt < attempts - 1 and is_transient_gh_failure(exc.stderr, exc.stdout, exc.returncode):
                time.sleep(2**attempt)
                continue
            raise
        except FileNotFoundError as exc:
            if cmd and cmd[0] == "gh":
                raise SystemExit("Missing GitHub CLI `gh` on PATH. Install it or add it to PATH before running this command.") from exc
            raise
    raise AssertionError("run_cmd exhausted without returning a result")


def gh_read_cmd(
    cmd: list[str],
    *,
    input_text: str | None = None,
    check: bool = False,
    retries: int = 3,
) -> subprocess.CompletedProcess:
    attempts = max(1, retries)
    for attempt in range(attempts):
        try:
            result = subprocess.run(cmd, input=input_text, text=True, capture_output=True, check=check)
            if result.returncode != 0 and cmd and cmd[0] == "gh" and is_transient_gh_failure(result.stderr, result.stdout, result.returncode):
                if attempt < attempts - 1:
                    time.sleep(2**attempt)
                    continue
            return result
        except subprocess.CalledProcessError as exc:
            if cmd and cmd[0] == "gh" and attempt < attempts - 1 and is_transient_gh_failure(exc.stderr, exc.stdout, exc.returncode):
                time.sleep(2**attempt)
                continue
            raise
        except FileNotFoundError as exc:
            if cmd and cmd[0] == "gh":
                raise SystemExit("Missing GitHub CLI `gh` on PATH. Install it or add it to PATH before running this command.") from exc
            raise
    raise AssertionError("gh_read_cmd exhausted without returning a result")


def gh_write_cmd(
    cmd: list[str],
    *,
    input_text: str | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess:
    return run_cmd(cmd, input_text=input_text, check=check)


def gh_read_json(args: list[str], *, retries: int = 3):
    result = gh_read_cmd(["gh", *args], check=True, retries=retries)
    return json.loads(result.stdout)


def gh_write_json(args: list[str], *, input_text: str | None = None):
    result = gh_write_cmd(["gh", *args], input_text=input_text, check=True)
    return json.loads(result.stdout)


def github_viewer_login(*, refresh: bool = False) -> str:
    global _GITHUB_VIEWER_LOGIN
    if _GITHUB_VIEWER_LOGIN and not refresh:
        return _GITHUB_VIEWER_LOGIN
    payload = gh_read_json(["api", "user"])
    _GITHUB_VIEWER_LOGIN = payload["login"]
    return _GITHUB_VIEWER_LOGIN


def list_pending_review_ids(repo: str, pr_number: str, login: str) -> set[str]:
    page = 1
    pending: set[str] = set()
    while True:
        reviews = gh_read_json(["api", f"repos/{repo}/pulls/{pr_number}/reviews?per_page=100&page={page}"])
        if not reviews:
            break
        for review in reviews:
            if review.get("state") != "PENDING":
                continue
            if (review.get("user") or {}).get("login") != login:
                continue
            pending.add(review["node_id"])
        page += 1
    return pending


def load_pull_request_head_sha(repo: str, pr_number: str) -> str:
    result = gh_read_cmd(
        ["gh", "pr", "view", pr_number, "--repo", repo, "--json", "headRefOid", "-q", ".headRefOid"],
        check=True,
    )
    return result.stdout.strip()


def session_engine(args: list[str], *, input_text: str | None = None, check: bool = False) -> subprocess.CompletedProcess:
    return run_cmd([sys.executable, str(SESSION_ENGINE), *args], input_text=input_text, check=check)


def _comment_nodes(connection: dict | None) -> list[dict]:
    if not isinstance(connection, dict):
        return []
    nodes = connection.get("nodes")
    return list(nodes) if isinstance(nodes, list) else []


def _comment_page_state(connection: dict | None) -> tuple[bool, str | None]:
    if not isinstance(connection, dict):
        return False, None
    page_info = connection.get("pageInfo")
    if not isinstance(page_info, dict):
        return False, None
    cursor = page_info.get("endCursor")
    return bool(page_info.get("hasNextPage")), cursor if isinstance(cursor, str) and cursor else None


def _load_thread_comments(thread_id: str, initial_connection: dict | None) -> list[dict]:
    comments = _comment_nodes(initial_connection)
    has_next_page, cursor = _comment_page_state(initial_connection)
    if not has_next_page:
        return comments

    query = """query($threadId:ID!,$after:String){
  node(id:$threadId){
    ... on PullRequestReviewThread{
      comments(first:100, after:$after){
        pageInfo{ hasNextPage endCursor }
        nodes{ url author{ login } }
      }
    }
  }
}"""
    seen_cursors: set[str | None] = set()
    while has_next_page and cursor not in seen_cursors:
        seen_cursors.add(cursor)
        cmd = ["api", "graphql", "-f", f"query={query}", "-F", f"threadId={thread_id}"]
        if cursor:
            cmd.extend(["-F", f"after={cursor}"])
        response = gh_read_json(cmd)
        node = ((response.get("data", {}) or {}).get("node", {}) or {})
        comment_connection = node.get("comments") if isinstance(node, dict) else {}
        comments.extend(_comment_nodes(comment_connection))
        has_next_page, cursor = _comment_page_state(comment_connection)
    return comments


def _viewer_reply_evidence(comments: list[dict], viewer_login: str) -> tuple[bool, str | None]:
    if not viewer_login:
        return False, None
    viewer_reply_url = None
    # The first thread comment is the original review comment, not reply evidence.
    for comment in comments[1:]:
        if not isinstance(comment, dict):
            continue
        author = comment.get("author")
        author_login = author.get("login") if isinstance(author, dict) else None
        comment_url = comment.get("url")
        if author_login == viewer_login and isinstance(comment_url, str) and comment_url.strip():
            viewer_reply_url = comment_url
    return bool(viewer_reply_url), viewer_reply_url


def list_threads(repo: str, pr_number: str) -> list[dict]:
    owner, name = repo.split("/", 1)
    try:
        viewer_login = github_viewer_login()
    except Exception:
        # Reply-evidence enrichment is best-effort; listing threads must still work when login lookup is unavailable.
        viewer_login = ""
    query = """query($owner:String!,$name:String!,$number:Int!,$after:String){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      reviewThreads(first:100, after:$after){
        pageInfo{ hasNextPage endCursor }
        nodes{
          id
          isResolved
          isOutdated
          path
          line
          comments(first:100){
            pageInfo{ hasNextPage endCursor }
            nodes{ url author{ login } }
          }
          firstComment: comments(first:1){ nodes{ url body } }
          latestComment: comments(last:1){ nodes{ url body } }
        }
      }
    }
  }
}"""

    threads: list[dict] = []
    cursor = None
    while True:
        cmd = ["api", "graphql", "-f", f"query={query}", "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"number={pr_number}"]
        if cursor:
            cmd.extend(["-F", f"after={cursor}"])
        response = gh_read_json(cmd)
        review_threads = response["data"]["repository"]["pullRequest"]["reviewThreads"]
        for node in review_threads["nodes"]:
            has_comment_connection = isinstance(node, dict) and isinstance(node.get("comments"), dict)
            comment_connection = node.get("comments") if has_comment_connection else None
            comments = _load_thread_comments(node["id"], comment_connection) if has_comment_connection else []
            latest = (node.get("latestComment", {}) or {}).get("nodes", [])
            first = (node.get("firstComment", {}) or {}).get("nodes", [])
            latest_node = latest[0] if latest else {}
            first_node = first[0] if first else {}
            viewer_reply_checked = bool(viewer_login) and has_comment_connection
            viewer_replied, viewer_reply_url = _viewer_reply_evidence(comments, viewer_login)
            threads.append(
                {
                    "id": node["id"],
                    "isResolved": node["isResolved"],
                    "isOutdated": node["isOutdated"],
                    "path": node.get("path"),
                    "line": node.get("line"),
                    "url": latest_node.get("url") or first_node.get("url"),
                    "body": latest_node.get("body") or first_node.get("body"),
                    "comment_source": "latest" if latest else ("first" if first else "none"),
                    "first_url": first_node.get("url"),
                    "latest_url": latest_node.get("url"),
                    "first_body": first_node.get("body"),
                    "latest_body": latest_node.get("body"),
                    "viewer_reply_checked": viewer_reply_checked,
                    "viewer_replied": viewer_replied,
                    "viewer_reply_url": viewer_reply_url,
                }
            )
        if not review_threads["pageInfo"]["hasNextPage"]:
            break
        cursor = review_threads["pageInfo"]["endCursor"]
    return threads


VALID_MODES = {"remote", "local", "mixed", "ingest"}
VALID_PRODUCERS = {"code-review", "json", "adapter"}


def shield_adapter_passthrough(argv: list[str] | None) -> list[str]:
    tokens = list(sys.argv[1:] if argv is None else argv)
    if "--" in tokens:
        return tokens
    if len(tokens) < 5:
        return tokens
    if tokens[0] not in {"local", "mixed", "ingest"}:
        return tokens
    if tokens[1] != "adapter":
        return tokens
    return [*tokens[:4], "--", *tokens[4:]]


def parse_dispatch(mode: str, parts: list[str]) -> tuple[str | None, str, str, list[str]]:
    """Shared dispatch parser used by both cr_loop.py and control_plane.py."""
    if mode == "remote":
        if len(parts) != 2:
            raise SystemExit("remote expects: <owner/repo> <pr_number>")
        return None, parts[0], parts[1], []

    if mode == "ingest":
        if len(parts) == 2:
            return "json", parts[0], parts[1], []
        if len(parts) >= 3:
            return parts[0], parts[1], parts[2], parts[3:]
        raise SystemExit("ingest expects: [producer] <owner/repo> <pr_number>")

    if len(parts) < 3:
        raise SystemExit(f"{mode} expects: <producer> <owner/repo> <pr_number> [adapter_cmd...]")
    return parts[0], parts[1], parts[2], parts[3:]
