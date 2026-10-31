"""Bind ordinary PR CI execution to the actual tested merge checkout."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from scripts.release import homebrew_support as shared

SCHEMA = "branch-validation.v1"
SOURCES = ("lint-and-test-3.12", "lint-and-test-3.13", "lint-and-test-3.14", "otel-minimum-versions")
IDENTITY_FIELDS = {"schema_version", "repository", "pr_number", "head_sha", "base_sha", "run_id", "run_attempt"}
CONTEXT_FIELDS = IDENTITY_FIELDS | {"tested_merge_sha", "merge_parents"}


def validate_context(row: dict, expected: dict) -> None:
    if not isinstance(row, dict) or set(row) != CONTEXT_FIELDS or any(row.get(key) != value for key, value in expected.items()):
        raise ValueError("validation context differs from the PR event identity")
    if row["schema_version"] != SCHEMA:
        raise ValueError("unsupported validation schema")
    if any(type(row[key]) is not int or row[key] < 1 for key in ("pr_number", "run_id", "run_attempt")):
        raise ValueError("invalid validation numeric identity")
    if not isinstance(row["repository"], str) or not re.fullmatch(r"[\w.-]+/[\w.-]+", row["repository"]):
        raise ValueError("invalid repository")
    if any(not isinstance(row[key], str) or not re.fullmatch(r"[a-f0-9]{40}", row[key])
           for key in ("head_sha", "base_sha", "tested_merge_sha")):
        raise ValueError("invalid tested revision")
    if row["merge_parents"] != [row["base_sha"], row["head_sha"]]:
        raise ValueError("tested commit is not the event base/head merge")


def event_identity() -> dict:
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        raise ValueError("only ordinary pull_request CI can produce validation evidence")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    repository = os.environ["GITHUB_REPOSITORY"]
    if event["repository"]["full_name"] != repository:
        raise ValueError("event repository differs from the workflow")
    return {
        "schema_version": SCHEMA, "repository": repository, "pr_number": event["number"],
        "head_sha": event["pull_request"]["head"]["sha"],
        "base_sha": event["pull_request"]["base"]["sha"],
        "run_id": int(os.environ["GITHUB_RUN_ID"]), "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
    }


def capture(expected: dict) -> dict:
    # Read the checkout once before tests; a later checkout cannot stand in for tested code.
    fields = shared.command(["git", "show", "-s", "--format=%H %P", "HEAD"]).stdout.strip().split()
    if len(fields) != 3:
        raise ValueError("CI must test a two-parent merge commit")
    context = {**expected, "tested_merge_sha": fields[0], "merge_parents": fields[1:]}
    validate_context(context, expected)
    return context


def validate_sources(rows: list[dict], expected: dict) -> dict:
    if (len(rows) != len(SOURCES) or any(not isinstance(row, dict) for row in rows)
            or {row.get("source") for row in rows} != set(SOURCES)):
        raise ValueError("all four unique CI execution sources are required")
    contexts = [{key: value for key, value in row.items() if key != "source"} for row in rows]
    for context in contexts:
        validate_context(context, expected)
    if any(context != contexts[0] for context in contexts[1:]):
        raise ValueError("CI jobs tested different merge revisions")
    return contexts[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("capture", "aggregate"))
    parser.add_argument("--source", choices=SOURCES)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = event_identity()
    if args.operation == "capture":
        if not args.source:
            parser.error("capture requires --source")
        payload = {**capture(expected), "source": args.source}
    else:
        if not args.directory:
            parser.error("aggregate requires --directory")
        paths = list(args.directory.rglob("*"))
        files = [path for path in paths if path.is_file()]
        if any(path.is_symlink() for path in paths) or any(path.name != "context.json" for path in files):
            raise ValueError("source artifacts must contain only context.json")
        payload = validate_sources([json.loads(path.read_text()) for path in files], expected)
    shared.write_json(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(shared.traced_main(main))
