#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os
import sys
import shlex
from pathlib import Path
import subprocess

SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    argv = list(sys.argv[1:] if argv is None else argv)
    resume_cmd: list[str] = []
    if "--" in argv:
        separator = argv.index("--")
        resume_cmd = argv[separator + 1 :]
        argv = argv[:separator]

    parser = argparse.ArgumentParser(description="Submit an action to a blocked loop and resume.")
    parser.add_argument("loop_request", help="Path to the loop-request JSON artifact.")
    parser.add_argument("--resolution", choices=["fix", "clarify", "defer", "reject"], required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--agent-id", default="agent")
    parser.add_argument("--reply-markdown")
    parser.add_argument("--commit-hash")
    parser.add_argument("--files")
    parser.add_argument("--severity", choices=["P1", "P2", "P3"])
    parser.add_argument("--why")
    parser.add_argument("--test-command")
    parser.add_argument("--test-result")
    parser.add_argument("--validation-cmd", action="append", default=[])
    parser.add_argument("--human", action="store_true", help="Emit human-oriented text instead of machine summary.")
    parser.add_argument("--machine", action="store_true", help="Compatibility alias.")
    args = parser.parse_args(argv)
    args.resume_cmd = resume_cmd
    return args


def safe_item_id(item: dict) -> str:
    return str(item.get("item_id", "unknown")).replace("/", "_").replace(":", "_")


def request_item(req: dict) -> dict | None:
    item = req.get("item")
    return item if isinstance(item, dict) else None


def repository_context(req: dict) -> tuple[str | None, str | None]:
    context = req.get("repository_context")
    if not isinstance(context, dict):
        context = {}
    repo = req.get("repo") or context.get("repo")
    pr_number = req.get("pr_number") or context.get("pr_number")
    return (str(repo) if repo else None, str(pr_number) if pr_number else None)


def is_runtime_request(req: dict) -> bool:
    return any(key in req for key in ("request_id", "lease_id", "agent_role", "repository_context"))


def error(message: str) -> int:
    print(f"Error: {message}", file=sys.stderr)
    return 2


def require_request_context(req: dict) -> tuple[str, str, dict] | None:
    repo, pr_number = repository_context(req)
    item = request_item(req)
    if not repo or not pr_number:
        error("request missing repository_context.repo or repository_context.pr_number")
        return None
    if not item:
        error("request missing item")
        return None
    return repo, pr_number, item


def require_runtime_identity(req: dict) -> bool:
    missing = [field for field in ("request_id", "lease_id") if not req.get(field)]
    if missing:
        error(f"runtime ActionRequest missing {', '.join(missing)}")
        return False
    return True


def parse_files(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_validation_commands(values: list[str], *, legacy: bool) -> list[dict[str, str]] | list[str]:
    if legacy:
        return values
    commands: list[dict[str, str]] = []
    for value in values:
        command, separator, result = value.rpartition("=")
        if not separator:
            command = value
            result = "passed"
        command = command.strip()
        result = result.strip()
        if command and result:
            commands.append({"command": command, "result": result})
    return commands


def build_fix_reply(args: argparse.Namespace, files: list[str]) -> dict:
    fields = {
        "summary": args.note,
        "commit_hash": args.commit_hash,
        "files": files or None,
        "severity": args.severity,
        "why": args.why,
        "test_command": args.test_command,
        "test_result": args.test_result,
    }
    return {key: value for key, value in fields.items() if value}


def validate_evidence(args: argparse.Namespace, item_kind: str, *, runtime: bool) -> bool:
    files = parse_files(args.files)
    if args.resolution == "fix":
        if item_kind == "github_thread" and (not args.commit_hash or not files):
            error("--resolution fix for github_thread requires --commit-hash and --files")
            return False
        if runtime and not files:
            error("--resolution fix for runtime ActionRequest requires --files")
            return False
        if runtime and not args.validation_cmd:
            error("--resolution fix for runtime ActionRequest requires --validation-cmd")
            return False
    else:
        if (runtime or item_kind == "github_thread") and not args.reply_markdown:
            target = "runtime ActionRequest" if runtime else item_kind
            error(f"--resolution {args.resolution} for {target} requires --reply-markdown")
            return False
        if runtime and not args.validation_cmd:
            error(f"--resolution {args.resolution} for runtime ActionRequest requires --validation-cmd")
            return False
    return True


def build_runtime_response(req: dict, args: argparse.Namespace) -> dict:
    files = parse_files(args.files)
    action = {
        "schema_version": str(req.get("schema_version") or "1.0"),
        "request_id": str(req["request_id"]),
        "lease_id": str(req["lease_id"]),
        "agent_id": args.agent_id,
        "resolution": args.resolution,
        "note": args.note,
        "validation_commands": parse_validation_commands(args.validation_cmd, legacy=False),
    }
    if files:
        action["files"] = files
    if args.reply_markdown:
        action["reply_markdown"] = args.reply_markdown
    if args.resolution == "fix":
        action["fix_reply"] = build_fix_reply(args, files)
    return action


def build_legacy_action(args: argparse.Namespace) -> dict:
    files = parse_files(args.files)
    action = {
        "resolution": args.resolution,
        "note": args.note,
    }
    if args.reply_markdown:
        action["reply_markdown"] = args.reply_markdown
    if any([args.commit_hash, files, args.severity, args.why, args.test_command, args.test_result]):
        action["fix_reply"] = {
            "commit_hash": args.commit_hash,
            "files": args.files,
            "severity": args.severity,
            "why": args.why,
            "test_command": args.test_command,
            "test_result": args.test_result,
        }
    if args.validation_cmd:
        action["validation_commands"] = parse_validation_commands(args.validation_cmd, legacy=True)
    return action


def bind_runtime_input(cmd: list[str], output_path: Path) -> list[str]:
    bound = list(cmd)
    output = str(output_path)
    for index, arg in enumerate(bound):
        if arg == "--input":
            if index + 1 < len(bound):
                bound[index + 1] = output
            else:
                bound.append(output)
            return bound
        if arg.startswith("--input="):
            bound[index] = f"--input={output}"
            return bound
    bound.extend(["--input", output])
    return bound


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    req_path = Path(args.loop_request)
    if not req_path.is_file():
        print(f"Error: loop-request file not found: {req_path}", file=sys.stderr)
        return 2

    try:
        req = json.loads(req_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"Error: invalid JSON in {req_path}", file=sys.stderr)
        return 2

    context = require_request_context(req)
    if context is None:
        return 2
    repo, pr_number, item = context
    runtime = is_runtime_request(req)
    if runtime and not require_runtime_identity(req):
        return 2

    item_kind = item.get("item_kind")
    if not validate_evidence(args, str(item_kind), runtime=runtime):
        return 2

    item_id = safe_item_id(item)
    action = build_runtime_response(req, args) if runtime else build_legacy_action(args)
    output_prefix = "action-response" if runtime else "fixer-payload"
    output_path = req_path.parent / f"{output_prefix}-{item_id}.json"

    output_path.write_text(json.dumps(action, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    script_path = req_path.parent / f"fixer-{item_id}.sh"
    script_path.write_text(f"#!/bin/sh\ncat {shlex.quote(str(output_path))}\n", encoding="utf-8")
    os.chmod(script_path, 0o755)

    cmd = list(args.resume_cmd)

    if cmd:
        if runtime:
            cmd = bind_runtime_input(cmd, output_path)
        elif not runtime:
            cmd.extend(["--fixer-cmd", str(script_path)])
        print(f"Resuming loop with submitted action '{args.resolution}'...")
        result = subprocess.run(cmd)
        return result.returncode

    print(f"Action '{args.resolution}' formulated for {item.get('item_id')}.")
    if runtime:
        print("To submit this response, run:")
        print(f"  gh-address-cr agent submit {repo} {pr_number} --input \"{output_path}\"")
    else:
        print("To resume the PR session, run your original loop command and append:")
        print(f"  --fixer-cmd \"{script_path}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
