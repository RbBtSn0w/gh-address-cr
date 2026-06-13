from __future__ import annotations

import shlex

# This module builds human-readable command strings shown to the user/agent as
# copy-paste suggestions. They are NOT executed here, so the goal is legibility,
# not shell-safe construction. Never feed the output of these helpers to a shell;
# build an argv list and run it without `shell=True` instead.


def quote_arg(value: str) -> str:
    text = str(value)
    # Keep angle-bracket placeholders (e.g. "<item_id>") literal so suggestions read
    # naturally. Real argument values are never of this shape.
    if text.startswith("<") and text.endswith(">"):
        return text
    return shlex.quote(text)


def shell_command(*parts: str) -> str:
    return " ".join(quote_arg(part) for part in parts)


def address(repo: str, pr_number: str) -> str:
    return shell_command("gh-address-cr", "address", repo, pr_number, "--lean")


def review_auto_simple(repo: str, pr_number: str) -> str:
    return shell_command("gh-address-cr", "review", "--auto-simple", repo, pr_number, "--lean")


def threads(repo: str, pr_number: str) -> str:
    return shell_command("gh-address-cr", "threads", repo, pr_number, "--lean")


def classify(repo: str, pr_number: str) -> str:
    return shell_command(
        "gh-address-cr",
        "agent",
        "classify",
        repo,
        pr_number,
        "<item_id>",
        "--classification",
        "fix",
        "--note",
        "<note>",
    )


def next_fixer(repo: str, pr_number: str) -> str:
    return shell_command(
        "gh-address-cr",
        "agent",
        "next",
        repo,
        pr_number,
        "--role",
        "fixer",
        "--agent-id",
        "<agent_id>",
    )


def batch_next(repo: str, pr_number: str, *, files: list[str] | None = None) -> str:
    parts = [
        "gh-address-cr",
        "agent",
        "next",
        repo,
        pr_number,
        "--batch",
        "--agent-id",
        "<agent_id>",
    ]
    if files:
        # `--files` is parsed as a comma-separated list downstream, so a path
        # containing a comma cannot round-trip. Drop such paths rather than emit a
        # suggestion that would be mis-split into bogus paths.
        usable = sorted(path for path in files if path and "," not in path)
        if usable:
            parts.extend(["--files", ",".join(usable)])
    return shell_command(*parts)


def submit(repo: str, pr_number: str, *, input_path: str = "response.json") -> str:
    return shell_command("gh-address-cr", "agent", "submit", repo, pr_number, "--input", input_path)


def submit_batch(repo: str, pr_number: str, *, input_path: str = "batch-response.json") -> str:
    return shell_command("gh-address-cr", "agent", "submit-batch", repo, pr_number, "--input", input_path)


def fix_all_input(repo: str, pr_number: str, *, input_path: str = "batch-response.json") -> str:
    return shell_command("gh-address-cr", "agent", "fix-all", repo, pr_number, "--input", input_path)


def fix_all_homogeneous(repo: str, pr_number: str) -> str:
    return shell_command(
        "gh-address-cr",
        "agent",
        "fix-all",
        repo,
        pr_number,
        "--commit",
        "<sha>",
        "--files",
        "<paths>",
        "--validation",
        "<cmd=passed>",
        "--homogeneous-reason",
        "<why>",
    )


def resolve_stale(repo: str, pr_number: str) -> str:
    return shell_command(
        "gh-address-cr",
        "agent",
        "resolve-stale",
        repo,
        pr_number,
        "--commit",
        "<sha>",
        "--files",
        "<paths>",
        "--validation",
        "<cmd=passed>",
        "--match-files",
    )


def publish(repo: str, pr_number: str) -> str:
    return shell_command("gh-address-cr", "agent", "publish", repo, pr_number)


def final_gate(repo: str, pr_number: str) -> str:
    return shell_command("gh-address-cr", "final-gate", repo, pr_number)


def common_summary_commands(repo: str, pr_number: str) -> dict[str, str]:
    return {
        "address": address(repo, pr_number),
        "review_auto_simple": review_auto_simple(repo, pr_number),
        "threads": threads(repo, pr_number),
        "classify": classify(repo, pr_number),
        "next": next_fixer(repo, pr_number),
        "batch_next": batch_next(repo, pr_number),
        "submit": submit(repo, pr_number),
        "submit_batch": submit_batch(repo, pr_number),
        "fix_all": fix_all_input(repo, pr_number),
        "fix_all_homogeneous": fix_all_homogeneous(repo, pr_number),
        "resolve_stale": resolve_stale(repo, pr_number),
        "publish": publish(repo, pr_number),
        "final_gate": final_gate(repo, pr_number),
    }

