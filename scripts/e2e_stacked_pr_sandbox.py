#!/usr/bin/env python3
"""Provision, inspect, and clean a real stacked-PR sandbox fixture on GitHub."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gh_address_cr.core.command_runner import run_cmd

API_VERSION = "2026-03-10"
DEFAULT_REPO = "RbBtSn0w/f2g-demo-portal-b-20260528"
SAFE_REPO_MARKERS = ("sandbox", "sample", "demo", "test", "fixture", "e2e")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class SandboxError(RuntimeError):
    pass


def gh_path() -> str:
    preferred = Path("/opt/homebrew/bin/gh")
    if preferred.is_file():
        return str(preferred)
    resolved = shutil.which("gh")
    if not resolved:
        raise SandboxError("GitHub CLI is required.")
    return resolved


def gh_api(endpoint: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    command = [
        gh_path(),
        "api",
        endpoint,
        "--method",
        method,
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        f"X-GitHub-Api-Version: {API_VERSION}",
    ]
    if payload is not None:
        command.extend(["--input", "-"])
    for attempt in range(3):
        completed = run_cmd(
            command,
            stdin=json.dumps(payload) if payload is not None else None,
            retries=1,
        )
        if completed.returncode == 0:
            output = completed.stdout.strip()
            return json.loads(output) if output else None
        detail = completed.stderr.strip() or completed.stdout.strip()
        if attempt < 2 and any(marker in detail.lower() for marker in ("unexpected eof", "tls", "timeout")):
            time.sleep(attempt + 1)
            continue
        raise SandboxError(f"GitHub API {method} {endpoint} failed: {detail}")
    raise SandboxError(f"GitHub API {method} {endpoint} failed after retries.")


def assert_sandbox_repo(repo: str, *, allow_non_sandbox: bool) -> dict[str, Any]:
    metadata = gh_api(f"repos/{repo}")
    searchable = f"{metadata.get('name', '')} {metadata.get('description') or ''}".lower()
    tokens = set(re.findall(r"[a-z0-9]+", searchable))
    if not allow_non_sandbox and not tokens.intersection(SAFE_REPO_MARKERS):
        raise SandboxError(
            f"Refusing non-sandbox repository {repo}; pass --allow-non-sandbox only after explicit authorization."
        )
    if metadata.get("archived") or metadata.get("disabled"):
        raise SandboxError(f"Repository {repo} is archived or disabled.")
    return metadata


def fixture_pull_title(run_id: str, layer: str) -> str:
    return f"test: stacked PR E2E {run_id} {layer}"


def fixture_pull_body(run_id: str, layer: str, position: int) -> str:
    return (
        "Automated gh-address-cr stacked-PR E2E fixture.\n\n"
        f"Run ID: `{run_id}`\nLayer: `{layer}`\nPosition: `{position}`\n"
        "Do not merge. Clean with scripts/e2e_stacked_pr_sandbox.py cleanup."
    )


def fixture_review_body(layer: str) -> str:
    return f"E2E review fixture for the {layer} stack layer. Resolve through gh-address-cr."


def validated_run_id(value: str | None) -> str:
    run_id = value or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise SandboxError("Run ID must contain only letters, numbers, dots, underscores, or hyphens.")
    return run_id


def validate_fixture_layer(
    layer: Any,
    *,
    position: int,
    expected_name: str,
    expected_base: str,
    run_id: str,
    seen_prs: set[int],
    seen_branches: set[str],
) -> str:
    if not isinstance(layer, dict):
        raise SandboxError(f"Manifest layer {position} must be an object.")
    expected_branch = f"e2e/gh-address-cr-stack-{run_id}-{expected_name}"
    expected_path = f"e2e/stack-{run_id}-{expected_name}.txt"
    try:
        observed_position = int(layer.get("position") or 0)
    except (TypeError, ValueError) as exc:
        raise SandboxError(f"Manifest layer {position} position is invalid.") from exc
    if layer.get("name") != expected_name or observed_position != position:
        raise SandboxError(f"Manifest layer {position} identity is invalid.")
    if layer.get("branch") != expected_branch or expected_branch in seen_branches:
        raise SandboxError(f"Manifest layer {position} branch is outside the fixture namespace.")
    if layer.get("base_branch") != expected_base:
        raise SandboxError(f"Manifest layer {position} base branch does not match the fixture chain.")
    if layer.get("path") != expected_path:
        raise SandboxError(f"Manifest layer {position} path is outside the fixture namespace.")
    if FULL_SHA_RE.fullmatch(str(layer.get("head_sha") or "")) is None:
        raise SandboxError(f"Manifest layer {position} head SHA is invalid.")
    try:
        pr_number = int(layer.get("pr_number"))
        comment_id = int(layer.get("review_comment_id"))
    except (TypeError, ValueError) as exc:
        raise SandboxError(f"Manifest layer {position} PR/comment identity is invalid.") from exc
    if pr_number < 1 or comment_id < 1 or pr_number in seen_prs:
        raise SandboxError(f"Manifest layer {position} PR/comment identity is invalid.")
    seen_prs.add(pr_number)
    seen_branches.add(expected_branch)
    return expected_branch


def validate_fixture_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != "gh_address_cr_stacked_pr_e2e.v1":
        raise SandboxError("Unsupported stacked-PR E2E manifest schema.")
    repo = str(manifest.get("repo") or "")
    if len(repo.split("/")) != 2 or any(not part for part in repo.split("/")):
        raise SandboxError("Manifest repository must use owner/name form.")
    run_id = str(manifest.get("run_id") or "")
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise SandboxError("Manifest run_id is missing or unsafe.")
    default_branch = str(manifest.get("default_branch") or "")
    if not default_branch:
        raise SandboxError("Manifest default_branch is required.")
    try:
        stack_number = int(manifest.get("stack_number"))
    except (TypeError, ValueError) as exc:
        raise SandboxError("Manifest stack_number must be a positive integer.") from exc
    if stack_number < 1:
        raise SandboxError("Manifest stack_number must be a positive integer.")
    layers = manifest.get("layers")
    if not isinstance(layers, list) or len(layers) != 3:
        raise SandboxError("Manifest must contain exactly three fixture layers.")

    expected_names = ("bottom", "middle", "top")
    expected_base = default_branch
    seen_prs: set[int] = set()
    seen_branches: set[str] = set()
    for position, (layer, expected_name) in enumerate(zip(layers, expected_names, strict=True), start=1):
        expected_base = validate_fixture_layer(
            layer,
            position=position,
            expected_name=expected_name,
            expected_base=expected_base,
            run_id=run_id,
            seen_prs=seen_prs,
            seen_branches=seen_branches,
        )


def create_blob(repo: str, content: str) -> str:
    return str(gh_api(f"repos/{repo}/git/blobs", method="POST", payload={"content": content, "encoding": "utf-8"})["sha"])


def create_layer_commit(repo: str, parent_sha: str, path: str, content: str, message: str) -> str:
    parent = gh_api(f"repos/{repo}/git/commits/{parent_sha}")
    blob_sha = create_blob(repo, content)
    tree = gh_api(
        f"repos/{repo}/git/trees",
        method="POST",
        payload={
            "base_tree": parent["tree"]["sha"],
            "tree": [{"path": path, "mode": "100644", "type": "blob", "sha": blob_sha}],
        },
    )
    commit = gh_api(
        f"repos/{repo}/git/commits",
        method="POST",
        payload={"message": message, "tree": tree["sha"], "parents": [parent_sha]},
    )
    return str(commit["sha"])


def create_ref(repo: str, branch: str, sha: str) -> None:
    gh_api(f"repos/{repo}/git/refs", method="POST", payload={"ref": f"refs/heads/{branch}", "sha": sha})


def existing_ref(repo: str, branch: str) -> str | None:
    try:
        return str(gh_api(f"repos/{repo}/git/ref/heads/{branch}")["object"]["sha"])
    except SandboxError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise


def existing_pull(repo: str, branch: str) -> dict[str, Any] | None:
    owner = repo.split("/", 1)[0]
    pulls = gh_api(f"repos/{repo}/pulls?state=all&head={owner}%3A{branch}")
    return pulls[0] if isinstance(pulls, list) and pulls else None


def create_pull(repo: str, *, head: str, base: str, title: str, body: str) -> dict[str, Any]:
    found = existing_pull(repo, head)
    if found is not None:
        return found
    try:
        return gh_api(
            f"repos/{repo}/pulls",
            method="POST",
            payload={"head": head, "base": base, "title": title, "body": body, "draft": False},
        )
    except SandboxError:
        found = existing_pull(repo, head)
        if found is not None:
            return found
        raise


def create_review_thread(repo: str, pr_number: int, *, commit_sha: str, path: str, layer: str) -> dict[str, Any]:
    body = fixture_review_body(layer)
    existing = gh_api(f"repos/{repo}/pulls/{pr_number}/comments")
    for comment in existing if isinstance(existing, list) else []:
        if comment.get("body") == body:
            return comment
    try:
        return gh_api(
            f"repos/{repo}/pulls/{pr_number}/comments",
            method="POST",
            payload={
                "body": body,
                "commit_id": commit_sha,
                "path": path,
                "line": 1,
                "side": "RIGHT",
            },
        )
    except SandboxError:
        existing = gh_api(f"repos/{repo}/pulls/{pr_number}/comments")
        for comment in existing if isinstance(existing, list) else []:
            if comment.get("body") == body:
                return comment
        raise


def provision(args: argparse.Namespace) -> dict[str, Any]:
    run_id = validated_run_id(args.run_id)
    metadata = assert_sandbox_repo(args.repo, allow_non_sandbox=args.allow_non_sandbox)
    default_branch = str((metadata.get("default_branch") or "main"))
    base_sha = str(gh_api(f"repos/{args.repo}/git/ref/heads/{default_branch}")["object"]["sha"])
    prefix = f"e2e/gh-address-cr-stack-{run_id}"
    parent_sha = base_sha
    base_branch = default_branch
    layers: list[dict[str, Any]] = []
    for position, layer_name in enumerate(("bottom", "middle", "top"), start=1):
        branch = f"{prefix}-{layer_name}"
        path = f"e2e/stack-{run_id}-{layer_name}.txt"
        commit_sha = existing_ref(args.repo, branch)
        if commit_sha is None:
            commit_sha = create_layer_commit(
                args.repo,
                parent_sha,
                path,
                f"gh-address-cr stacked PR E2E layer: {layer_name}\n",
                f"test: add {layer_name} stacked PR fixture",
            )
            create_ref(args.repo, branch, commit_sha)
        pull = create_pull(
            args.repo,
            head=branch,
            base=base_branch,
            title=fixture_pull_title(run_id, layer_name),
            body=fixture_pull_body(run_id, layer_name, position),
        )
        layers.append(
            {
                "name": layer_name,
                "position": position,
                "branch": branch,
                "base_branch": base_branch,
                "path": path,
                "head_sha": commit_sha,
                "pr_number": int(pull["number"]),
                "pr_url": pull["html_url"],
            }
        )
        parent_sha = commit_sha
        base_branch = branch

    existing_stacks = gh_api(f"repos/{args.repo}/stacks?pull_request={layers[0]['pr_number']}")
    if isinstance(existing_stacks, list) and existing_stacks:
        stack = existing_stacks[0]
    else:
        try:
            stack = gh_api(
                f"repos/{args.repo}/stacks",
                method="POST",
                payload={"pull_requests": [layer["pr_number"] for layer in layers]},
            )
        except SandboxError:
            existing_stacks = gh_api(f"repos/{args.repo}/stacks?pull_request={layers[0]['pr_number']}")
            if not isinstance(existing_stacks, list) or not existing_stacks:
                raise
            stack = existing_stacks[0]
    for layer in layers:
        comment = create_review_thread(
            args.repo,
            layer["pr_number"],
            commit_sha=layer["head_sha"],
            path=layer["path"],
            layer=layer["name"],
        )
        layer["review_comment_id"] = comment["id"]
        layer["review_comment_url"] = comment["html_url"]

    manifest = {
        "schema_version": "gh_address_cr_stacked_pr_e2e.v1",
        "repo": args.repo,
        "run_id": run_id,
        "default_branch": default_branch,
        "stack_number": int(stack["number"]),
        "stack_node_id": stack.get("node_id"),
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "layers": layers,
    }
    write_manifest(args.manifest, manifest)
    return manifest


def verify(manifest: dict[str, Any]) -> dict[str, Any]:
    validate_fixture_manifest(manifest)
    repo = str(manifest["repo"])
    stack_number = int(manifest["stack_number"])
    stack = gh_api(f"repos/{repo}/stacks/{stack_number}")
    observed_prs = [int(row["number"]) for row in stack.get("pull_requests", [])]
    expected_prs = [int(layer["pr_number"]) for layer in manifest["layers"]]
    if observed_prs != expected_prs:
        raise SandboxError(f"Stack membership mismatch: expected {expected_prs}, observed {observed_prs}")
    if int(stack.get("number") or 0) != stack_number:
        raise SandboxError("Live stack number does not match the fixture manifest.")
    expected_node_id = str(manifest.get("stack_node_id") or "")
    observed_node_id = str(stack.get("node_id") or "")
    if expected_node_id and observed_node_id and observed_node_id != expected_node_id:
        raise SandboxError("Live stack node identity does not match the fixture manifest.")
    positions: list[dict[str, Any]] = []
    for layer in manifest["layers"]:
        pull = gh_api(f"repos/{repo}/pulls/{layer['pr_number']}")
        expected_title = fixture_pull_title(str(manifest["run_id"]), str(layer["name"]))
        expected_body = fixture_pull_body(
            str(manifest["run_id"]), str(layer["name"]), int(layer["position"])
        )
        if pull.get("title") != expected_title or pull.get("body") != expected_body:
            raise SandboxError(f"PR #{layer['pr_number']} is not the recorded fixture pull request.")
        if str((pull.get("head") or {}).get("ref") or "") != str(layer["branch"]):
            raise SandboxError(f"PR #{layer['pr_number']} head branch does not match the fixture manifest.")
        if str((pull.get("head") or {}).get("sha") or "") != str(layer["head_sha"]):
            raise SandboxError(f"PR #{layer['pr_number']} head revision does not match the fixture manifest.")
        if str((pull.get("base") or {}).get("ref") or "") != str(layer["base_branch"]):
            raise SandboxError(f"PR #{layer['pr_number']} base branch does not match the fixture chain.")
        stack_context = pull.get("stack")
        if not isinstance(stack_context, dict):
            raise SandboxError(f"PR #{layer['pr_number']} has no REST stack context.")
        positions.append(
            {
                "pr_number": int(layer["pr_number"]),
                "expected_position": int(layer["position"]),
                "observed_position": int(stack_context["position"]),
                "stack_number": int(stack_context["number"]),
                "stack_size": int(stack_context["size"]),
            }
        )
        comments = gh_api(f"repos/{repo}/pulls/{layer['pr_number']}/comments")
        comment = next(
            (
                row
                for row in comments if isinstance(row, dict) and int(row.get("id") or 0) == int(layer["review_comment_id"])
            ),
            None,
        ) if isinstance(comments, list) else None
        if (
            comment is None
            or comment.get("body") != fixture_review_body(str(layer["name"]))
            or comment.get("path") != layer["path"]
        ):
            raise SandboxError(f"PR #{layer['pr_number']} review comment is not the recorded fixture thread.")
    if any(row["expected_position"] != row["observed_position"] for row in positions):
        raise SandboxError(f"Stack position mismatch: {positions}")
    if any(row["stack_number"] != stack_number or row["stack_size"] != len(manifest["layers"]) for row in positions):
        raise SandboxError(f"Stack identity mismatch: {positions}")
    return {"status": "VERIFIED", "repo": repo, "stack_number": stack_number, "positions": positions}


def run_runtime_json(arguments: list[str], *, accepted_exit_codes: tuple[int, ...] = (0,)) -> dict[str, Any]:
    completed = run_cmd(
        [sys.executable, "-m", "gh_address_cr", *arguments],
        retries=1,
    )
    if completed.returncode not in accepted_exit_codes:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SandboxError(f"gh-address-cr {' '.join(arguments)} failed: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SandboxError(f"gh-address-cr {' '.join(arguments)} returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SandboxError(f"gh-address-cr {' '.join(arguments)} returned a non-object payload.")
    return payload


def exercise(manifest: dict[str, Any]) -> dict[str, Any]:
    """Address fixture threads, prove each layer gate, then prove the aggregate stack gate."""
    verification = verify(manifest)
    repo = str(manifest["repo"])
    layer_results: list[dict[str, Any]] = []
    for layer in manifest["layers"]:
        pr_number = str(layer["pr_number"])
        address = run_runtime_json(["address", repo, pr_number], accepted_exit_codes=(0, 5))
        item_id = address.get("item_id")
        if address.get("status") != "PASSED":
            if not isinstance(item_id, str) or not item_id.startswith("github-thread:"):
                raise SandboxError(f"PR #{pr_number} did not expose a claimable GitHub review thread.")
            selected_thread = next(
                (
                    row
                    for row in address.get("threads", [])
                    if isinstance(row, dict) and row.get("item_id") == item_id
                ),
                None,
            )
            if (
                selected_thread is None
                or selected_thread.get("body") != fixture_review_body(str(layer["name"]))
                or selected_thread.get("path") != layer["path"]
            ):
                raise SandboxError(f"PR #{pr_number} selected an unrelated review thread; refusing to resolve it.")
            run_runtime_json(
                [
                    "agent",
                    "resolve",
                    repo,
                    pr_number,
                    item_id,
                    "--disposition",
                    "reject",
                    "--why",
                    "Synthetic E2E fixture; no product change is required.",
                    "--agent-id",
                    "stacked-pr-e2e",
                ]
            )
            run_runtime_json(["agent", "publish", repo, pr_number, "--agent-id", "stacked-pr-e2e"])
        gate = run_runtime_json(["final-gate", repo, pr_number, "--machine", "--no-auto-clean"])
        if gate.get("status") != "PASSED" or gate.get("completion_scope") != "pull_request":
            raise SandboxError(f"Layer gate for PR #{pr_number} did not pass with pull_request scope.")
        layer_results.append(
            {
                "pr_number": int(pr_number),
                "position": int(layer["position"]),
                "address_status": address.get("status"),
                "resolved_item_id": item_id if address.get("status") != "PASSED" else None,
                "gate_status": gate.get("status"),
                "completion_scope": gate.get("completion_scope"),
                "completion_summary_line": gate.get("completion_summary_line"),
            }
        )

    top_pr = str(manifest["layers"][-1]["pr_number"])
    stack_gate = run_runtime_json(
        [
            "final-gate",
            repo,
            top_pr,
            "--stack",
            "--machine",
            "--no-auto-clean",
            "--require-required-checks",
        ]
    )
    if stack_gate.get("status") != "PASSED" or stack_gate.get("completion_scope") != "stack_segment":
        raise SandboxError(f"Aggregate stack gate did not pass: {stack_gate.get('reason_code')}")
    stack_gate_details = stack_gate.get("stack_gate")
    expected_members = [str(layer["pr_number"]) for layer in manifest["layers"]]
    if (
        stack_gate.get("check_requirement") != "required"
        or not isinstance(stack_gate_details, dict)
        or stack_gate_details.get("check_requirement") != "required"
        or str(stack_gate_details.get("selected_pr_number") or "") != top_pr
        or [str(number) for number in stack_gate_details.get("covered_pr_numbers") or []]
        != expected_members
    ):
        raise SandboxError("Aggregate stack gate did not prove the expected required-check stack segment.")
    return {
        "status": "PASSED",
        "repo": repo,
        "stack_number": verification["stack_number"],
        "layers": layer_results,
        "stack_gate": {
            "status": stack_gate.get("status"),
            "completion_scope": stack_gate.get("completion_scope"),
            "check_requirement": stack_gate.get("check_requirement"),
            "completion_summary_line": stack_gate.get("completion_summary_line"),
            "covered_pr_numbers": stack_gate_details.get("covered_pr_numbers"),
        },
    }


def cleanup(manifest: dict[str, Any]) -> dict[str, Any]:
    validate_fixture_manifest(manifest)
    verify(manifest)
    repo = str(manifest["repo"])
    stack_number = int(manifest["stack_number"])
    gh_api(f"repos/{repo}/stacks/{stack_number}/unstack", method="POST")
    for layer in reversed(manifest["layers"]):
        gh_api(f"repos/{repo}/pulls/{layer['pr_number']}", method="PATCH", payload={"state": "closed"})
        gh_api(f"repos/{repo}/git/refs/heads/{layer['branch']}", method="DELETE")
    return {"status": "CLEANED", "repo": repo, "stack_number": stack_number}


def read_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SandboxError(f"Manifest not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "gh_address_cr_stacked_pr_e2e.v1":
        raise SandboxError(f"Invalid manifest: {path}")
    return payload


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("action", choices=("provision", "verify", "exercise", "cleanup"))
    result.add_argument("--repo", default=DEFAULT_REPO)
    result.add_argument("--run-id", default="")
    result.add_argument("--manifest", type=Path, required=True)
    result.add_argument("--allow-non-sandbox", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.action == "provision":
            result = provision(args)
        else:
            manifest = read_manifest(args.manifest)
            assert_sandbox_repo(str(manifest["repo"]), allow_non_sandbox=args.allow_non_sandbox)
            actions = {"verify": verify, "exercise": exercise, "cleanup": cleanup}
            result = actions[args.action](manifest)
    except (SandboxError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 5
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
