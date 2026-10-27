#!/usr/bin/env python3
"""Repeatable finding-resolution eval: real review findings, each run N times.

Each run builds a hermetic PR fixture from a sample in
`tests/evals/finding-resolution/samples/`: a git checkout whose feature branch
is the PR head, a bare `origin` it pushes to, and a fake `gh` whose review
threads carry the real bot comment. An agent handles the PR with the packaged
skill and this checkout's runtime, then deterministic graders score the run:

- legal_state: final-gate passed; every thread is resolved and carries a reply
  the runtime published; the agent made no direct `gh` writes; the fake modelled
  every runtime `gh` call.
- effective_fix: each thread's disposition is one the sample expects; the hidden
  oracle and the fixture's own tests pass on the pushed PR head.
- consistent_evidence: every fix cites a commit in the PR and carries validation
  evidence; recorded validation commands that are runnable pass on the pushed head.

    .venv/bin/python scripts/eval_finding_resolution.py run --agent scripted
    .venv/bin/python scripts/eval_finding_resolution.py run --agent claude --model claude-sonnet-5-5 --repeats 5
    .venv/bin/python scripts/eval_finding_resolution.py report build/evals/finding-resolution/<run-id>

`--agent scripted` follows each sample's reference solution through the CLI and
must score 100%; it is the offline control in tests/test_finding_resolution_eval.py.
`--agent claude` launches headless Claude Code and spends API budget. Runs are
serial, telemetry export is disabled, and results land in build/ (git-ignored).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "tests" / "evals" / "finding-resolution"
SAMPLES_DIR = EVAL_DIR / "samples"
FAKE_GH = EVAL_DIR / "fake_gh.py"
JOURNEY_FAKE_GH = ROOT / "tests" / "fixtures" / "agent_journey" / "fake_gh.py"
RESULTS_ROOT = ROOT / "build" / "evals" / "finding-resolution"
SKILL_PAYLOAD = ROOT / "skill"
REPO_OWNER = "eval-fixture"
AGENT_LOGIN = "agent-login"
SCRIPTED_AGENT_ID = "eval-reference"
FIXTURE_TEST_COMMAND = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
ORACLE_MODULE = "eval_oracle_test"
# Host-session and credential variables a nested agent must not inherit.
SCRUBBED_ENV = re.compile(r"^(CLAUDECODE|CLAUDE_CODE_|CLAUDE_AGENT_SDK_|CLAUDE_PID$|CLAUDE_EFFORT$|CLAUDE_PREVIEW_|"
                          r"AI_AGENT$|GH_|GITHUB|OTEL_|PYTHONPATH$|VIRTUAL_ENV$)|_PAT$|_TOKEN$")
CLAUDE_TOOLS = "Bash,Read,Edit,Write,Glob,Grep,Skill"
GH_WRITE_MARKERS = ("mutation", "addPullRequestReviewThreadReply", "resolveReviewThread")


class EvalError(RuntimeError):
    pass


def git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    if completed.returncode != 0:
        raise EvalError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


# -- samples -------------------------------------------------------------------


def sample_ids() -> list[str]:
    return sorted(path.parent.name for path in SAMPLES_DIR.glob("*/sample.json"))


def load_sample(sample_id: str) -> dict[str, Any]:
    path = SAMPLES_DIR / sample_id / "sample.json"
    if not path.is_file():
        raise EvalError(f"unknown sample {sample_id!r}; known: {', '.join(sample_ids())}")
    sample = json.loads(path.read_text(encoding="utf-8"))
    sample["dir"] = path.parent
    return sample


def overlay(tree: Path, checkout: Path) -> None:
    for source in sorted(tree.rglob("*")):
        if source.is_file():
            target = checkout / source.relative_to(tree)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def anchor_line(text: str, anchor: str) -> int:
    lines = [number for number, line in enumerate(text.splitlines(), start=1) if anchor in line]
    if len(lines) != 1:
        raise EvalError(f"anchor {anchor!r} must match exactly one line, matched {len(lines)}")
    return lines[0]


# -- fixture -------------------------------------------------------------------


@dataclass
class Fixture:
    sample: dict[str, Any]
    run_dir: Path
    checkout: Path
    remote: Path
    state_path: Path
    callers_path: Path
    unhandled_path: Path
    state_dir: Path
    env: dict[str, str]
    repo: str
    pr: str
    base_sha: str
    pr_commits: list[str]

    def gh_state(self) -> dict[str, Any]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def gh_calls(self) -> list[dict[str, Any]]:
        if not self.callers_path.exists():
            return []
        return [json.loads(line) for line in self.callers_path.read_text(encoding="utf-8").splitlines() if line]


def runtime_bin() -> Path:
    """The bin directory of the interpreter running this script; it must provide this checkout's runtime."""
    bin_dir = Path(sys.executable).parent
    if not (bin_dir / "gh-address-cr").is_file():
        raise EvalError(f"{bin_dir} has no gh-address-cr; run with the dev venv (scripts/dev_setup.sh, .venv/bin/python)")
    return bin_dir


def fixture_env(run_dir: Path, bin_dir: Path, conversation_id: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not SCRUBBED_ENV.search(key)}
    gh_config = run_dir / "gh-config"
    gh_config.mkdir()
    gitconfig = run_dir / "gitconfig"
    gitconfig.write_text("[user]\n\tname = eval-agent\n\temail = eval-agent@example.test\n[commit]\n\tgpgsign = false\n",
                         encoding="utf-8")
    env.update(
        {
            "PATH": f"{bin_dir}:{runtime_bin()}:{env.get('PATH', '')}",
            "GH_CONFIG_DIR": str(gh_config),
            "GH_PROMPT_DISABLED": "1",
            "GIT_CONFIG_GLOBAL": str(gitconfig),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GH_ADDRESS_CR_STATE_DIR": str(run_dir / "state"),
            "GH_ADDRESS_CR_CONVERSATION_ID": conversation_id,
            "DISABLE_TELEMETRY": "1",
            "FAKE_GH_STATE": str(run_dir / "gh-state.json"),
            "FAKE_GH_REMOTE": str(run_dir / "origin.git"),
            "FAKE_GH_CALLERS": str(run_dir / "gh-callers.jsonl"),
            "FAKE_GH_CALLS": str(run_dir / "gh-calls.jsonl"),
            "FAKE_GH_UNHANDLED": str(run_dir / "gh-unhandled.log"),
            "FAKE_GH_DELEGATE": str(JOURNEY_FAKE_GH),
        }
    )
    return env


def commit_trees(sample: dict[str, Any], checkout: Path, env: dict[str, str]) -> list[str]:
    shas = []
    for commit in sample["commits"]:
        overlay(sample["dir"] / commit["tree"], checkout)
        git(checkout, "add", "-A", env=env)
        git(checkout, "commit", "-q", "-m", commit["message"], env=env)
        shas.append(git(checkout, "rev-parse", "HEAD", env=env))
    return shas


def thread_state(sample: dict[str, Any], checkout: Path, shas: list[str], env: dict[str, str]) -> list[dict[str, Any]]:
    threads = []
    for index, thread in enumerate(sample["threads"], start=1):
        anchor_sha = shas[thread.get("anchor_commit", len(shas)) - 1]
        text = git(checkout, "show", f"{anchor_sha}:{thread['path']}", env=env)
        line = anchor_line(text, thread["anchor"])
        body = (sample["dir"] / thread["body"]).read_text(encoding="utf-8")
        threads.append(
            {
                "id": thread["id"],
                "isResolved": False,
                "isOutdated": bool(thread.get("outdated")),
                "path": thread["path"],
                # GitHub reports no current line for an outdated thread.
                "line": None if thread.get("outdated") else line,
                "comments": [{"url": f"https://github.test/review/{index}", "author": thread["author"], "body": body}],
            }
        )
    return threads


def build_fixture(sample: dict[str, Any], run_dir: Path, conversation_id: str) -> Fixture:
    run_dir.mkdir(parents=True)
    bin_dir = run_dir / "bin"
    bin_dir.mkdir()
    shutil.copyfile(FAKE_GH, bin_dir / "gh")
    (bin_dir / "gh").chmod(0o755)
    env = fixture_env(run_dir, bin_dir, conversation_id)
    remote, checkout = run_dir / "origin.git", run_dir / "checkout"
    git(run_dir, "init", "-q", "--bare", "-b", "main", str(remote), env=env)
    checkout.mkdir()
    git(checkout, "init", "-q", "-b", "main", env=env)
    overlay(sample["dir"] / "base", checkout)
    git(checkout, "add", "-A", env=env)
    git(checkout, "commit", "-q", "-m", "chore: initial import", env=env)
    base_sha = git(checkout, "rev-parse", "HEAD", env=env)
    head_ref = sample["pull_request"]["head_ref"]
    git(checkout, "checkout", "-q", "-b", head_ref, env=env)
    shas = commit_trees(sample, checkout, env)
    git(checkout, "remote", "add", "origin", str(remote), env=env)
    git(checkout, "push", "-q", "-u", "origin", "main", head_ref, env=env)
    # The skill is installed per project; keep it out of what the agent commits.
    shutil.copytree(SKILL_PAYLOAD, checkout / ".claude" / "skills" / "gh-address-cr")
    with (checkout / ".git" / "info" / "exclude").open("a", encoding="utf-8") as handle:
        handle.write(".claude/\n")
    repo = f"{REPO_OWNER}/{sample['id']}"
    pr = str(sample["pull_request"]["number"])
    state = {
        "repo": repo,
        "pr_number": pr,
        "head_ref": head_ref,
        "head_sha": shas[-1],
        "base_sha": base_sha,
        "commits": shas,
        "files": [],
        "title": sample["pull_request"]["title"],
        "body": sample["pull_request"]["body"],
        "threads": thread_state(sample, checkout, shas, env),
    }
    state_path = run_dir / "gh-state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return Fixture(
        sample=sample,
        run_dir=run_dir,
        checkout=checkout,
        remote=remote,
        state_path=state_path,
        callers_path=run_dir / "gh-callers.jsonl",
        unhandled_path=run_dir / "gh-unhandled.log",
        state_dir=run_dir / "state",
        env=env,
        repo=repo,
        pr=pr,
        base_sha=base_sha,
        pr_commits=shas,
    )


# -- agents --------------------------------------------------------------------


def run_runtime(fixture: Fixture, *args: str) -> dict[str, Any]:
    completed = subprocess.run(
        [str(runtime_bin() / "gh-address-cr"), *args],
        cwd=fixture.checkout,
        env=fixture.env,
        capture_output=True,
        text=True,
    )
    stdout = completed.stdout.strip()
    payload: dict[str, Any] = {}
    if "{" in stdout:
        try:
            payload = json.loads(stdout[stdout.find("{"):])
        except ValueError:
            payload = {}
    payload["_exit_code"] = completed.returncode
    payload["_output"] = completed.stdout + completed.stderr
    return payload


def scripted_resolve_args(fixture: Fixture, item: dict[str, Any], commit: str, files: list[str]) -> list[str]:
    args = ["agent", "resolve", fixture.repo, fixture.pr, f"github-thread:{item['thread']}"]
    if item["disposition"] == "fix":
        args += ["--commit", commit, "--summary", item["summary"], "--why", item["why"]]
        for path in files:
            args += ["--file", path]
        args += ["--validation", f"{shlex.join(['python3', *FIXTURE_TEST_COMMAND[1:]])}=passed"]
    else:
        args += ["--disposition", item["disposition"], "--why", item["why"]]
    if item.get("stale"):
        args.append("--stale")
    return args + ["--agent-id", SCRIPTED_AGENT_ID]


def run_scripted(fixture: Fixture) -> dict[str, Any]:
    """Follow the sample's reference solution the way SKILL.md routes a GitHub thread."""
    reference = fixture.sample["reference"]
    steps: list[dict[str, Any]] = []
    commit = ""
    files: list[str] = []
    if reference.get("tree"):
        overlay(fixture.sample["dir"] / reference["tree"], fixture.checkout)
        git(fixture.checkout, "add", "-A", env=fixture.env)
        git(fixture.checkout, "commit", "-q", "-m", reference["message"], env=fixture.env)
        git(fixture.checkout, "push", "-q", "origin", "HEAD", env=fixture.env)
        commit = git(fixture.checkout, "rev-parse", "HEAD", env=fixture.env)
    elif reference.get("cite_commit"):
        commit = fixture.pr_commits[reference["cite_commit"] - 1]
    if commit:
        files = git(fixture.checkout, "show", "--name-only", "--format=", commit, env=fixture.env).splitlines()
    commands = [["address", fixture.repo, fixture.pr, "--lean"]]
    commands += [scripted_resolve_args(fixture, item, commit, files) for item in reference["items"]]
    commands += [["agent", "publish", fixture.repo, fixture.pr], ["final-gate", fixture.repo, fixture.pr]]
    for args in commands:
        result = run_runtime(fixture, *args)
        steps.append({"command": args[:2], "exit_code": result["_exit_code"], "status": result.get("status"),
                      "reason_code": result.get("reason_code")})
    return {"agent": "scripted", "exit_code": 0, "steps": steps}


CLAUDE_PROMPT = "/gh-address-cr address {repo} {pr}"
RUNTIME_STATUS_RE = re.compile(r'"(status|reason_code)":\s*"([A-Z0-9_]+)"')
GATE_REASON_RE = re.compile(r"reason_code=([A-Z0-9_]+)")


def claude_trace(transcript: Path) -> dict[str, Any]:
    """Runtime commands the agent ran, their outcomes, and the run's result event."""
    commands: dict[str, dict[str, Any]] = {}
    result: dict[str, Any] = {}
    for line in transcript.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "result":
            result = event
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Bash":
                command = str((block.get("input") or {}).get("command") or "")
                subcommand = runtime_subcommand(command)
                if subcommand:
                    commands[block["id"]] = {"command": subcommand, "codes": []}
            if block.get("type") == "tool_result" and block.get("tool_use_id") in commands:
                text = tool_result_text(block.get("content"))
                codes = [value for key, value in RUNTIME_STATUS_RE.findall(text) if key == "reason_code"]
                codes += GATE_REASON_RE.findall(text)
                commands[block["tool_use_id"]]["codes"] = sorted(set(codes))
    return {"commands": list(commands.values()), "result": result}


def tool_result_text(content: Any) -> str:
    """A tool result is a string or a list of content blocks; only their text matters."""
    if isinstance(content, list):
        return "\n".join(str(block.get("text") or "") for block in content if isinstance(block, dict))
    return str(content or "")


def runtime_subcommand(command: str) -> str | None:
    """`agent resolve`-style label without arguments, so traces stay free of paths and text.

    None when the command only mentions the runtime, e.g. `cat` of a path under a skill directory.
    """
    match = re.search(r"(?:gh-address-cr|gh_address_cr)\s+((?:agent|telemetry)\s+[a-z-]+|[a-z-]+)", command)
    return match.group(1) if match else None


def run_claude(fixture: Fixture, options: argparse.Namespace, out_dir: Path) -> dict[str, Any]:
    claude = shutil.which("claude", path=fixture.env["PATH"])
    if not claude:
        raise EvalError("claude CLI not found on PATH")
    transcript = out_dir / "transcript.jsonl"
    command = [
        claude, "-p", CLAUDE_PROMPT.format(repo=fixture.repo, pr=fixture.pr),
        "--model", options.model,
        "--output-format", "stream-json", "--verbose",
        # Project settings only: no user CLAUDE.md, user skills, plugins, or MCP servers.
        "--setting-sources", "project", "--strict-mcp-config",
        "--no-session-persistence",
        "--allowedTools", options.allowed_tools,
        "--max-turns", str(options.max_turns),
        "--max-budget-usd", str(options.max_budget_usd),
    ]
    started = time.monotonic()
    with transcript.open("w", encoding="utf-8") as handle:
        try:
            completed = subprocess.run(command, cwd=fixture.checkout, env=fixture.env, stdout=handle,
                                       stderr=subprocess.PIPE, text=True, timeout=options.timeout)
            exit_code, stderr = completed.returncode, completed.stderr
        except subprocess.TimeoutExpired:
            exit_code, stderr = 124, "timed out"
    trace = claude_trace(transcript)
    result = trace["result"]
    return {
        "agent": "claude",
        "model": options.model,
        "exit_code": exit_code,
        "stderr_tail": stderr[-400:],
        "duration_s": round(time.monotonic() - started, 1),
        "result_subtype": result.get("subtype"),
        "is_error": result.get("is_error"),
        "num_turns": result.get("num_turns"),
        "permission_denials": len(result.get("permission_denials") or []),
        "cost_usd": result.get("total_cost_usd"),
        "steps": trace["commands"],
        "final_message": str(result.get("result") or "")[-1500:],
    }


# -- graders -------------------------------------------------------------------


def latest(paths: list[Path]) -> Path | None:
    return max(paths, key=lambda path: path.stat().st_mtime) if paths else None


def runtime_artifacts(fixture: Fixture) -> dict[str, Any]:
    session_path = latest(list(fixture.state_dir.rglob("session.json")))
    report_path = latest(list(fixture.state_dir.rglob("efficiency-report.json")))
    ledger = []
    for path in fixture.state_dir.rglob("evidence.jsonl"):
        ledger += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    passed = any("reason_code: PASSED" in path.read_text(encoding="utf-8")
                 for path in fixture.state_dir.rglob("audit_summary.md"))
    session = json.loads(session_path.read_text(encoding="utf-8")) if session_path else {}
    return {
        "items": session.get("items", {}),
        "lease_events": len(session.get("lease_events") or []),
        "report": json.loads(report_path.read_text(encoding="utf-8")) if report_path else {},
        "ledger": ledger,
        "final_gate_passed": passed,
    }


def is_gh_write(args: list[str]) -> bool:
    if args[:2] in (["pr", "comment"], ["pr", "review"], ["pr", "merge"], ["pr", "close"], ["pr", "edit"]):
        return True
    if any(marker in arg for arg in args for marker in GH_WRITE_MARKERS):
        return True
    methods = [args[index + 1].upper() for index, arg in enumerate(args[:-1]) if arg in ("-X", "--method")]
    return any(method != "GET" for method in methods)


def grade_legal_state(fixture: Fixture, artifacts: dict[str, Any]) -> dict[str, Any]:
    threads = fixture.gh_state()["threads"]
    ledger_replies = {row["payload"].get("reply_url") for row in artifacts["ledger"]
                      if row.get("event_type") == "reply_posted"}
    agent_replies = [row["url"] for thread in threads for row in thread["comments"] if row["author"] == AGENT_LOGIN]
    calls = fixture.gh_calls()
    checks = {
        "final_gate_passed": artifacts["final_gate_passed"],
        "all_threads_resolved": all(thread["isResolved"] for thread in threads),
        "every_thread_replied": all(any(row["author"] == AGENT_LOGIN for row in thread["comments"])
                                    for thread in threads),
        "replies_ledger_backed": all(url in ledger_replies for url in agent_replies),
        "no_direct_gh_writes": not any(call["caller"] == "agent" and is_gh_write(call["args"]) for call in calls),
        "fake_modelled_runtime_calls": all(call.get("handled", True) for call in calls if call["caller"] == "runtime"),
    }
    return {"passed": all(checks.values()), "checks": checks}


def run_in(clone: Path, command: list[str], env: dict[str, str]) -> bool:
    try:
        return subprocess.run(command, cwd=clone, env=env, capture_output=True, text=True, timeout=300).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def clone_pushed_head(fixture: Fixture, name: str) -> Path:
    clone = fixture.run_dir / name
    git(fixture.run_dir, "clone", "-q", "--branch", fixture.sample["pull_request"]["head_ref"], str(fixture.remote),
        str(clone), env=fixture.env)
    return clone


def run_oracle(fixture: Fixture, clone: Path) -> bool:
    shutil.copyfile(fixture.sample["dir"] / fixture.sample["oracle"], clone / f"{ORACLE_MODULE}.py")
    return run_in(clone, [sys.executable, "-m", "unittest", ORACLE_MODULE], fixture.env)


def thread_dispositions(fixture: Fixture, items: dict[str, Any]) -> dict[str, str | None]:
    dispositions = {}
    for thread in fixture.sample["threads"]:
        item = items.get(f"github-thread:{thread['id']}") or {}
        response = item.get("accepted_response") or {}
        dispositions[thread["id"]] = response.get("resolution") or item.get("decision")
    return dispositions


def grade_effective_fix(fixture: Fixture, artifacts: dict[str, Any], clone: Path) -> dict[str, Any]:
    dispositions = thread_dispositions(fixture, artifacts["items"])
    checks = {
        "dispositions_expected": all(dispositions[thread["id"]] in thread["expected"]
                                     for thread in fixture.sample["threads"]),
        "fixture_tests_pass": run_in(clone, FIXTURE_TEST_COMMAND, fixture.env),
    }
    checks["oracle_passes"] = run_oracle(fixture, clone)
    return {"passed": all(checks.values()), "checks": checks, "dispositions": dispositions}


def runnable_validation(command: str) -> list[str] | None:
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    executable = os.path.basename(argv[0]) if argv else ""
    if executable.startswith("python"):
        return [sys.executable, *argv[1:]]
    # Agents record `python3 -m unittest ...` as `unittest ...`; it names the same run.
    if executable == "unittest":
        return [sys.executable, "-m", "unittest", *argv[1:]]
    return None


def oracle_at(fixture: Fixture, sha: str) -> bool:
    clone = clone_pushed_head(fixture, "cited")
    git(clone, "checkout", "-q", sha, env=fixture.env)
    return run_oracle(fixture, clone)


def grade_evidence(fixture: Fixture, artifacts: dict[str, Any], clone: Path) -> dict[str, Any]:
    head_ref = fixture.sample["pull_request"]["head_ref"]
    pr_commits = git(fixture.remote, "rev-list", "--reverse", f"{fixture.base_sha}..refs/heads/{head_ref}",
                     env=fixture.env).split()
    fixes = [item for item in artifacts["items"].values()
             if (item.get("accepted_response") or {}).get("resolution") == "fix"]
    resolved, validations = [], []
    for item in fixes:
        response = item["accepted_response"]
        cited = str((response.get("fix_reply") or {}).get("commit_hash") or "")
        resolved.append(next((sha for sha in pr_commits if cited and sha.startswith(cited)), None))
        validations.append([row.get("command", "") for row in response.get("validation_commands") or []])
    runnable = [argv for commands in validations for argv in map(runnable_validation, commands) if argv]
    in_pr = [sha for sha in resolved if sha]
    checks = {
        "fix_commits_in_pr": all(resolved),
        "every_fix_has_validation": all(validations),
        "runnable_validations_pass": all(run_in(clone, argv, fixture.env) for argv in runnable),
        # Reachability alone accepts a citation of the commit that introduced the defect.
        "oracle_passes_at_cited_commit": not fixes
        or (len(in_pr) == len(resolved) and oracle_at(fixture, max(in_pr, key=pr_commits.index))),
    }
    return {"passed": all(checks.values()), "checks": checks, "validation_commands": validations,
            "runnable_validation_count": len(runnable),
            # Reported, not gated: SKILL.md allows label-only validation such as `unit-tests=passed`.
            "fix_count": len(validations),
            "fixes_with_rerunnable_validation": sum(1 for commands in validations
                                                    if any(map(runnable_validation, commands)))}


def grade(fixture: Fixture) -> dict[str, Any]:
    artifacts = runtime_artifacts(fixture)
    clone = clone_pushed_head(fixture, "grade")
    evidence = grade_evidence(fixture, artifacts, clone)
    report = artifacts["report"]
    return {
        "legal_state": grade_legal_state(fixture, artifacts),
        "effective_fix": grade_effective_fix(fixture, artifacts, clone),
        "consistent_evidence": evidence,
        "runtime": report.get("runtime"),
        "efficiency": {key: report.get(key) for key in
                       ("success_rate", "needs_action_count", "inefficiency_flags", "error_prone_operations")},
        # What the runtime itself saw, so an axis label is not only the sample's claim.
        "runtime_observed": {
            "outdated_items": sorted(item_id for item_id, item in artifacts["items"].items() if item.get("is_outdated")),
            "lease_events": artifacts["lease_events"],
        },
        "agent_gh_calls": [call["args"][:2] for call in fixture.gh_calls() if call["caller"] == "agent"],
        "new_commits": len(git(fixture.remote, "rev-list", f"{fixture.pr_commits[-1]}..refs/heads/"
                               f"{fixture.sample['pull_request']['head_ref']}", env=fixture.env).split()),
    }


# -- runs and report -----------------------------------------------------------

CRITERIA = ("legal_state", "effective_fix", "consistent_evidence")
# Reason codes an agent normally meets on the documented path; anything else is a deviation.
# BLOCKING_ITEMS_REMAIN is the `threads` status for open items, not a rejection.
EXPECTED_CODES = {"PASSED", "WAITING_FOR_SIMPLE_ADDRESS", "READY_FOR_FINAL_GATE", "COMPLETE", "BLOCKING_ITEMS_REMAIN"}
AXIS_KEYWORDS = (
    ("lease", ("LEASE", "CLAIM", "OWNER")),
    ("verification", ("VALIDATION", "TEST")),
    ("classification", ("CLASSIFICATION", "DISPOSITION", "DECLINE")),
    ("recovery", ("STALE", "CLOSED", "ALREADY_RESOLVED", "REPLY_EVIDENCE", "COMMIT_NOT_IN_PR", "REVISION",
                  "STACK_CONTEXT", "PERSISTENCE", "RECOVER", "RESUME")),
    ("input", ("INVALID", "MISSING", "PARTIAL", "UNKNOWN", "USAGE", "AMBIGUOUS", "NO_ACTIVE", "AXIS")),
)


def reason_axis(code: str) -> str:
    for axis, keywords in AXIS_KEYWORDS:
        if any(keyword in code for keyword in keywords):
            return axis
    return "other"


def run_one(sample_id: str, repeat: int, options: argparse.Namespace, out_dir: Path, work_root: Path) -> dict[str, Any]:
    sample = load_sample(sample_id)
    run_out = out_dir / sample_id / f"run-{repeat}"
    run_out.mkdir(parents=True, exist_ok=True)
    fixture = build_fixture(sample, work_root / f"{sample_id}-{repeat}", f"eval-{out_dir.name}-{sample_id}-{repeat}")
    try:
        agent = run_scripted(fixture) if options.agent == "scripted" else run_claude(fixture, options, run_out)
        record = {"sample": sample_id, "axis": sample["axis"], "repeat": repeat, "agent": agent, **grade(fixture)}
    except EvalError as exc:
        record = {"sample": sample_id, "axis": sample["axis"], "repeat": repeat, "error": str(exc)}
    finally:
        if not options.keep:
            shutil.rmtree(fixture.run_dir, ignore_errors=True)
    record["passed"] = all((record.get(name) or {}).get("passed") for name in CRITERIA)
    (run_out / "run.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def deviations(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Off-path reason codes with the step that hit them and the runtime step the agent ran next."""
    steps = (record.get("agent") or {}).get("steps", [])
    found = []
    for index, step in enumerate(steps):
        for code in step.get("codes") or [step.get("reason_code")]:
            if code and code not in EXPECTED_CODES:
                following = steps[index + 1]["command"] if index + 1 < len(steps) else None
                found.append({"code": code, "step": step["command"], "next_step": following})
    return found


def friction_codes(record: dict[str, Any]) -> list[str]:
    return [row["code"] for row in deviations(record)]


def fix_count(record: dict[str, Any]) -> int:
    return (record.get("consistent_evidence") or {}).get("fix_count", 0)


def verified_remediation(record: dict[str, Any]) -> bool:
    """Passed, and every fix left validation an independent grader re-ran: the run's evidence is replayable."""
    evidence = record.get("consistent_evidence") or {}
    count = fix_count(record)
    return bool(record["passed"] and count and evidence.get("fixes_with_rerunnable_validation", 0) == count)


def summarize_deviations(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    table: dict[str, dict[str, Any]] = {}
    for record in records:
        for row in deviations(record):
            entry = table.setdefault(row["code"], {"axis": reason_axis(row["code"]), "occurrences": 0, "runs": [],
                                                   "runs_passed": 0, "steps": {}, "next_steps": {}})
            entry["occurrences"] += 1
            run = f"{record['sample']}#{record['repeat']}"
            if run not in entry["runs"]:
                entry["runs"].append(run)
                entry["runs_passed"] += 1 if record["passed"] else 0
            for key, value in (("steps", row["step"]), ("next_steps", row["next_step"] or "none")):
                entry[key][value] = entry[key].get(value, 0) + 1
    return dict(sorted(table.items(), key=lambda item: -item[1]["occurrences"]))


def rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {"count": numerator, "of": denominator, "rate": round(numerator / denominator, 3) if denominator else None}


def summarize_sample(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dispositions = [json.dumps((row.get("effective_fix") or {}).get("dispositions"), sort_keys=True) for row in rows]
    failed_checks: dict[str, int] = {}
    for row in rows:
        for name in CRITERIA:
            for check, ok in ((row.get(name) or {}).get("checks") or {}).items():
                if not ok:
                    failed_checks[f"{name}.{check}"] = failed_checks.get(f"{name}.{check}", 0) + 1
    costs = [row["agent"]["cost_usd"] for row in rows if (row.get("agent") or {}).get("cost_usd") is not None]
    return {
        "axis": rows[0]["axis"],
        "runs": len(rows),
        "passed": sum(1 for row in rows if row["passed"]),
        **{name: sum(1 for row in rows if (row.get(name) or {}).get("passed")) for name in CRITERIA},
        "dispositions_consistent": len(set(dispositions)) == 1,
        "fix_runs": sum(1 for row in rows if fix_count(row)),
        "verified_runs": sum(1 for row in rows if verified_remediation(row)),
        "fixes": sum((row.get("consistent_evidence") or {}).get("fix_count", 0) for row in rows),
        "rerunnable_fixes": sum((row.get("consistent_evidence") or {}).get("fixes_with_rerunnable_validation", 0)
                                for row in rows),
        "dispositions_seen": sorted(set(dispositions)),
        "failed_checks": dict(sorted(failed_checks.items())),
        "errors": [row["error"] for row in rows if row.get("error")],
        "cost_usd": round(sum(costs), 4) if costs else None,
    }


def aggregate(records: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    by_sample: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_sample.setdefault(record["sample"], []).append(record)
    fixes = sum(fix_count(row) for row in records)
    rerunnable = sum((row.get("consistent_evidence") or {}).get("fixes_with_rerunnable_validation", 0) for row in records)
    costs = [row["agent"]["cost_usd"] for row in records if (row.get("agent") or {}).get("cost_usd") is not None]
    return {
        "schema": "gh_address_cr_finding_eval_summary.v1",
        **meta,
        "runs": len(records),
        "passed": sum(1 for row in records if row["passed"]),
        "samples": {sample: summarize_sample(rows) for sample, rows in sorted(by_sample.items())},
        # Consistency is gated; rerunnability is reported separately so a label-only record is visible
        # without being scored as a failed fix.
        "evidence_consistency": rate(sum(1 for row in records if (row.get("consistent_evidence") or {}).get("passed")),
                                     len(records)),
        "evidence_rerunnability": rate(rerunnable, fixes),
        "verified_remediation": rate(sum(1 for row in records if verified_remediation(row)),
                                     sum(1 for row in records if fix_count(row))),
        "deviations": summarize_deviations(records),
        "total_cost_usd": round(sum(costs), 4) if costs else None,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"# Finding-resolution eval `{summary['run_id']}`",
        "",
        f"- Agent: `{summary['agent']}`" + (f" (`{summary['model']}`)" if summary.get("model") else ""),
        f"- Runtime: `{summary.get('runtime_commit')}`; repeats per sample: {summary['repeats']}",
        f"- Passed: **{summary['passed']}/{summary['runs']}** runs"
        + (f"; cost ${summary['total_cost_usd']:.2f}" if summary.get("total_cost_usd") is not None else ""),
        f"- Evidence consistency: {render_rate(summary['evidence_consistency'], 'runs')}",
        f"- Evidence rerunnability: {render_rate(summary['evidence_rerunnability'], 'fixes')}",
        f"- **Verified remediation** (passed, and every fix's validation re-ran): "
        f"{render_rate(summary['verified_remediation'], 'runs with fixes')}",
        "",
        "| Sample | Axis | Pass | Legal state | Effective fix | Evidence | Rerunnable evidence | Verified | Same disposition |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for sample, row in summary["samples"].items():
        runs = row["runs"]
        rerunnable = f"{row['rerunnable_fixes']}/{row['fixes']} fixes" if row["fixes"] else "n/a"
        verified = f"{row['verified_runs']}/{row['fix_runs']}" if row["fix_runs"] else "n/a"
        lines.append(
            f"| {sample} | {row['axis']} | {row['passed']}/{runs} | {row['legal_state']}/{runs} | "
            f"{row['effective_fix']}/{runs} | {row['consistent_evidence']}/{runs} | {rerunnable} | {verified} | "
            f"{'yes' if row['dispositions_consistent'] else 'no'} |"
        )
    failures = [(sample, row) for sample, row in summary["samples"].items() if row["failed_checks"] or row["errors"]]
    if failures:
        lines += ["", "## Failed checks", ""]
        for sample, row in failures:
            detail = ", ".join(f"`{check}` x{count}" for check, count in row["failed_checks"].items())
            lines.append(f"- {sample}: {detail or 'harness error'}" + (f" ({'; '.join(row['errors'])})" if row["errors"] else ""))
    if summary["deviations"]:
        lines += ["", "## Workflow deviations", "",
                  "| Reason code | Axis | Occurrences | Runs | Hit on | Next step | Runs passed after |",
                  "|---|---|---|---|---|---|---|"]
        for code, row in summary["deviations"].items():
            lines.append(
                f"| `{code}` | {row['axis']} | {row['occurrences']} | {', '.join(row['runs'])} | "
                f"{render_counts(row['steps'])} | {render_counts(row['next_steps'])} | "
                f"{row['runs_passed']}/{len(row['runs'])} |"
            )
    return "\n".join(lines) + "\n"


def render_rate(value: dict[str, Any], unit: str) -> str:
    if not value["of"]:
        return "n/a"
    return f"{value['count']}/{value['of']} {unit} ({value['rate']:.0%})"


def render_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"`{name}` x{count}" for name, count in sorted(counts.items(), key=lambda item: -item[1]))


def write_summary(out_dir: Path, records: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    summary = aggregate(records, meta)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(render_markdown(summary), encoding="utf-8")
    return summary


def run_eval(options: argparse.Namespace) -> dict[str, Any]:
    import tempfile

    run_id = options.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{options.agent}"
    out_dir = options.output_root / run_id
    out_dir.mkdir(parents=True, exist_ok=False)
    meta = {
        "run_id": run_id,
        "agent": options.agent,
        "model": options.model if options.agent == "claude" else None,
        "repeats": options.repeats,
        "runtime_commit": git(ROOT, "rev-parse", "--short", "HEAD"),
        "runtime_dirty": bool(git(ROOT, "status", "--porcelain", "--", "src", "skill")),
    }
    records = []
    # Fixtures live outside this repository so a nested agent cannot discover its
    # AGENTS.md, the oracles, or the reference solutions by walking up from its cwd.
    work_root = Path(tempfile.mkdtemp(prefix="gh-address-cr-eval-"))
    try:
        for repeat in range(1, options.repeats + 1):
            for sample_id in options.samples or sample_ids():
                record = run_one(sample_id, repeat, options, out_dir, work_root)
                records.append(record)
                print(f"{sample_id} run {repeat}: {'PASS' if record['passed'] else 'FAIL'}", file=sys.stderr, flush=True)
                write_summary(out_dir, records, meta)
    finally:
        if options.keep:
            print(f"fixtures kept in {work_root}", file=sys.stderr)
        else:
            shutil.rmtree(work_root, ignore_errors=True)
    return write_summary(out_dir, records, meta)


def load_record(path: Path) -> dict[str, Any]:
    """A graded run. Steps are re-derived from the raw transcript, so a reporting change never needs a re-run."""
    record = json.loads(path.read_text(encoding="utf-8"))
    transcript = path.parent / "transcript.jsonl"
    if (record.get("agent") or {}).get("agent") == "claude" and transcript.is_file():
        record["agent"]["steps"] = claude_trace(transcript)["commands"]
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run the eval and write summary.json and summary.md.")
    run.add_argument("--agent", choices=("scripted", "claude"), required=True)
    run.add_argument("--model", default="claude-sonnet-5-5", help="Model for --agent claude.")
    run.add_argument("--repeats", type=int, default=1)
    run.add_argument("--sample", dest="samples", action="append", choices=sample_ids(), help="Repeatable; default all.")
    run.add_argument("--max-turns", type=int, default=80)
    run.add_argument("--max-budget-usd", type=float, default=5.0, help="Per-run budget for --agent claude.")
    run.add_argument("--allowed-tools", default=CLAUDE_TOOLS,
                     help="--allowedTools for --agent claude; narrow Bash with patterns such as 'Bash(git:*)'.")
    run.add_argument("--timeout", type=int, default=1800, help="Per-run agent timeout in seconds.")
    run.add_argument("--output-root", type=Path, default=RESULTS_ROOT)
    run.add_argument("--run-id")
    run.add_argument("--keep", action="store_true", help="Keep fixture directories for inspection.")
    report = commands.add_parser("report", help="Re-render summary.md from the run.json files of a run.")
    report.add_argument("run_dir", type=Path)
    options = parser.parse_args(argv)
    if options.command == "report":
        records = [load_record(path) for path in sorted(options.run_dir.glob("*/run-*/run.json"))]
        meta = json.loads((options.run_dir / "summary.json").read_text(encoding="utf-8"))
        summary = write_summary(options.run_dir, records, {key: meta[key] for key in
                                ("run_id", "agent", "model", "repeats", "runtime_commit", "runtime_dirty")})
    else:
        summary = run_eval(options)
    sys.stdout.write(render_markdown(summary))
    return 0 if summary["passed"] == summary["runs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
