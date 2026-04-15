#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SESSION_ENGINE = SCRIPT_DIR / "session_engine.py"
_GITHUB_VIEWER_LOGIN: str | None = None


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


def audit_summary_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "audit_summary.md"


def handled_threads_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "handled_threads.txt"


def findings_file(repo: str, pr_number: str, name: str = "code-review-findings.json") -> Path:
    return workspace_dir(repo, pr_number) / name


def reply_file(repo: str, pr_number: str, name: str) -> Path:
    return workspace_dir(repo, pr_number) / name


def loop_artifact_file(repo: str, pr_number: str, name: str) -> Path:
    return workspace_dir(repo, pr_number) / name


def validation_file(repo: str, pr_number: str, name: str) -> Path:
    return workspace_dir(repo, pr_number) / name


def github_pr_cache_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "github_pr_cache.json"


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


def audit_event(action: str, status: str, repo: str, pr_number: str, audit_id: str = "default", message: str = "", details=None):
    entry = {
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "action": action,
        "status": status,
        "repo": repo,
        "pr": pr_number,
        "audit_id": audit_id,
        "message": message,
        "details": details or {},
    }
    with audit_log_file(repo, pr_number).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


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
    _ = retries
    try:
        return subprocess.run(cmd, input=input_text, text=True, capture_output=True, check=check)
    except FileNotFoundError as exc:
        if cmd and cmd[0] == "gh":
            raise SystemExit("Missing GitHub CLI `gh` on PATH. Install it or add it to PATH before running this command.") from exc
        raise


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


def list_threads(repo: str, pr_number: str) -> list[dict]:
    owner, name = repo.split("/", 1)
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
            latest = (node.get("latestComment", {}) or {}).get("nodes", [])
            first = (node.get("firstComment", {}) or {}).get("nodes", [])
            latest_node = latest[0] if latest else {}
            first_node = first[0] if first else {}
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
