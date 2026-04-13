#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SESSION_ENGINE = SCRIPT_DIR / "session_engine.py"


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


def snapshot_file(repo: str, pr_number: str) -> Path:
    return state_dir() / f"{normalize_repo(repo)}__pr{pr_number}__threads.jsonl"


def session_file(repo: str, pr_number: str) -> Path:
    return state_dir() / f"{normalize_repo(repo)}__pr{pr_number}__session.json"


def audit_log_file(repo: str, pr_number: str) -> Path:
    return state_dir() / f"{normalize_repo(repo)}__pr{pr_number}__audit.jsonl"


def audit_summary_file(repo: str, pr_number: str) -> Path:
    return state_dir() / f"{normalize_repo(repo)}__pr{pr_number}__audit_summary.md"


def handled_threads_file(repo: str, pr_number: str) -> Path:
    return state_dir() / f"{normalize_repo(repo)}__pr{pr_number}__handled_threads.txt"


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


def run_cmd(cmd: list[str], *, input_text: str | None = None, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=input_text, text=True, capture_output=True, check=check)


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
        cmd = ["gh", "api", "graphql", "-f", f"query={query}", "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"number={pr_number}"]
        if cursor:
            cmd.extend(["-F", f"after={cursor}"])
        response = json.loads(run_cmd(cmd, check=True).stdout)
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
