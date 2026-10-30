#!/usr/bin/env python3
"""Eval fake `gh`: the agent-journey fake with a PR head that follows pushes.

Before every call the PR head, commits, and changed files are re-read from the
bare `origin` named by FAKE_GH_REMOTE, so an agent's `git push` reaches the
runtime the way it reaches GitHub. Each call is logged with its caller (the
runtime or the agent) so graders can tell runtime-owned side effects from direct
`gh` use. The agent-facing reads `pr view` and `pr diff` are answered here;
every other call goes to the journey fake, which fails loudly on calls it does
not model.
"""

import fcntl
import json
import os
import runpy
import subprocess
import sys

STATE_PATH = os.environ["FAKE_GH_STATE"]
REMOTE = os.environ["FAKE_GH_REMOTE"]
CALLERS_PATH = os.environ["FAKE_GH_CALLERS"]
UNHANDLED_PATH = os.environ["FAKE_GH_UNHANDLED"]
DELEGATE = os.environ["FAKE_GH_DELEGATE"]
PR_FIELDS = ("number", "title", "body", "state", "isDraft", "url", "headRefName", "headRefOid", "baseRefName")


def git(*args):
    return subprocess.run(
        ["git", f"--git-dir={REMOTE}", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def caller():
    """`runtime` when the parent is a Python process running gh-address-cr, else `agent`."""
    command = subprocess.run(
        ["ps", "-o", "command=", "-p", str(os.getppid())], capture_output=True, text=True
    ).stdout.strip()
    executable = os.path.basename(command.split(" ", 1)[0]).lower() if command else ""
    is_runtime = executable.startswith("python") and ("gh_address_cr" in command or "gh-address-cr" in command)
    return "runtime" if is_runtime else "agent"


def sync_pr_head(state):
    head = git("rev-parse", f"refs/heads/{state['head_ref']}")
    base = state["base_sha"]
    statuses = {"A": "added", "M": "modified", "D": "removed"}
    status_by_name = {}
    for line in git("diff", "--name-status", base, head).splitlines():
        code, name = line.split("\t", 1)
        status_by_name[name] = statuses.get(code[:1], "modified")
    files = []
    for line in git("diff", "--numstat", base, head).splitlines():
        added, deleted, name = line.split("\t", 2)
        # numstat prints `-` for binary files.
        additions = int(added) if added.isdigit() else 0
        deletions = int(deleted) if deleted.isdigit() else 0
        files.append(
            {
                "filename": name,
                "status": status_by_name.get(name, "modified"),
                "additions": additions,
                "deletions": deletions,
                "changes": additions + deletions,
            }
        )
    state["head_sha"] = head
    state["commits"] = git("rev-list", "--reverse", f"{base}..{head}").split()
    state["files"] = files


def pr_view(args, state):
    fields = {
        "number": int(state["pr_number"]),
        "title": state["title"],
        "body": state["body"],
        "state": "OPEN",
        "isDraft": False,
        "url": f"https://github.test/{state['repo']}/pull/{state['pr_number']}",
        "headRefName": state["head_ref"],
        "headRefOid": state["head_sha"],
        "baseRefName": "main",
    }
    if "--json" in args:
        requested = args[args.index("--json") + 1].split(",")
        print(json.dumps({name: fields[name] for name in requested if name in PR_FIELDS}))
    else:
        print(f"title:\t{state['title']}\nstate:\tOPEN\nnumber:\t{state['pr_number']}\n--\n{state['body']}")
    raise SystemExit(0)


def unhandled_size():
    return os.path.getsize(UNHANDLED_PATH) if os.path.exists(UNHANDLED_PATH) else 0


def dispatch(args):
    with open(STATE_PATH, encoding="utf-8") as handle:
        state = json.load(handle)
    sync_pr_head(state)
    with open(STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    if args[:2] == ["pr", "view"]:
        pr_view(args, state)
    if args[:2] == ["pr", "diff"]:
        print(git("diff", state["base_sha"], state["head_sha"]))
        raise SystemExit(0)
    runpy.run_path(DELEGATE, run_name="__main__")


def dispatch_call():
    args = sys.argv[1:]
    record = {"caller": caller(), "args": args}
    before = unhandled_size()
    try:
        dispatch(args)
    finally:
        # The journey fake records calls it does not model; attribute each one.
        record["handled"] = unhandled_size() == before
        with open(CALLERS_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")


def main():
    # Even reads refresh shared state; keep parallel runtime reads out of a partial JSON write.
    with open(STATE_PATH + ".lock", "a", encoding="utf-8") as state_lock:
        fcntl.flock(state_lock, fcntl.LOCK_EX)
        dispatch_call()


if __name__ == "__main__":
    main()
