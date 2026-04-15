#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from python_common import audit_event, gh_read_cmd, gh_read_json, gh_write_json, run_cmd


SCRIPT_DIR = Path(__file__).resolve().parent
SESSION_ENGINE = SCRIPT_DIR / "session_engine.py"


def load_item(repo: str, pr_number: str, item_id: str) -> dict:
    result = run_cmd([sys.executable, str(SESSION_ENGINE), "list-items", repo, pr_number], check=True)
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item["item_id"] == item_id:
            return item
    raise SystemExit(f"Item not found in session: {item_id}")


def gh_json(args: list[str]) -> object:
    return gh_read_json(args)


def load_pr_files(repo: str, pr_number: str) -> list[dict]:
    files: list[dict] = []
    page = 1
    while True:
        response = gh_json(["api", f"repos/{repo}/pulls/{pr_number}/files", "-F", "per_page=100", "-F", f"page={page}"])
        if not response:
            break
        if not isinstance(response, list):
            raise SystemExit("Expected a JSON array when listing PR files.")
        files.extend(response)
        page += 1
    return files


def compute_diff_position(files: list[dict], target_path: str, target_line: int) -> int:
    patch = None
    for file_entry in files:
        if file_entry.get("filename") == target_path:
            patch = file_entry.get("patch")
            break
    if not patch:
        raise SystemExit(f"Unable to find patch for {target_path}")

    position = 0
    right_line = None
    for raw_line in patch.splitlines():
        if raw_line.startswith("@@"):
            header = raw_line.split("@@")[1].strip()
            _, right = header.split(" ")
            start = right.split(",")[0]
            right_line = int(start.lstrip("+")) - 1
            continue

        position += 1
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            right_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            continue
        else:
            right_line += 1

        if right_line == target_line:
            return position

    raise SystemExit(f"Unable to compute diff position for {target_path}:{target_line}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a local finding back to GitHub review comments.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True)
    parser.add_argument("--audit-id", default="default")
    parser.add_argument("local_item_id")
    args = parser.parse_args()

    if not SESSION_ENGINE.exists():
        print(f"Missing session engine: {SESSION_ENGINE}", file=sys.stderr)
        return 1

    item = load_item(args.repo, args.pr, args.local_item_id)
    if item["item_kind"] != "local_finding":
        print(f"Only local_finding items can be published: {args.local_item_id}", file=sys.stderr)
        return 1

    path_value = item.get("path")
    line_value = item.get("line")
    if not path_value or line_value is None:
        print(f"Publishing requires item path and line: {args.local_item_id}", file=sys.stderr)
        return 1

    comment_body = (
        "Local AI review finding:\n\n"
        f"Title: {item.get('title', 'Local review finding')}\n\n"
        f"{item.get('body', '')}"
    )

    head_sha_result = gh_read_cmd(
        ["gh", "pr", "view", args.pr, "--repo", args.repo, "--json", "headRefOid", "-q", ".headRefOid"],
        check=True,
    )
    head_sha = head_sha_result.stdout.strip()
    files = load_pr_files(args.repo, args.pr)
    diff_position = compute_diff_position(files, path_value, int(line_value))

    if args.dry_run:
        print(f"[dry-run] Would publish local finding: {args.local_item_id}")
        print(
            f"repo={args.repo} pr={args.pr} path={path_value} "
            f"line={line_value} position={diff_position} commit={head_sha}"
        )
        print("-----")
        print(comment_body)
        print("-----")
        audit_event(
            "publish_finding",
            "dry-run",
            args.repo,
            args.pr,
            args.audit_id,
            "Previewed local finding publication",
            {
                "item_id": args.local_item_id,
                "path": path_value,
                "line": int(line_value),
                "position": diff_position,
                "commit_id": head_sha,
            },
        )
        return 0

    payload = {
        "body": comment_body,
        "commit_id": head_sha,
        "path": path_value,
        "position": diff_position,
    }
    comment = gh_write_json(
        ["api", f"repos/{args.repo}/pulls/{args.pr}/comments", "--method", "POST", "--input", "-"],
        input_text=json.dumps(payload),
    )
    sys.stdout.write(json.dumps(comment))

    run_cmd(
        [
            sys.executable,
            str(SESSION_ENGINE),
            "mark-published",
            args.repo,
            args.pr,
            args.local_item_id,
            "--published-ref",
            str(comment["id"]),
            "--url",
            comment.get("html_url", ""),
            "--note",
            "Published local finding to GitHub review comments.",
            "--actor",
            "publish_finding",
        ],
        check=True,
    )
    audit_event(
        "publish_finding",
        "ok",
        args.repo,
        args.pr,
        args.audit_id,
        "Published local finding to GitHub review comments",
        {
            "item_id": args.local_item_id,
            "path": path_value,
            "line": int(line_value),
            "position": diff_position,
            "commit_id": head_sha,
            "comment_id": comment.get("id"),
            "comment_url": comment.get("html_url", ""),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
