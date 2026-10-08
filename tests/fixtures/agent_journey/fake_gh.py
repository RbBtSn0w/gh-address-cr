#!/usr/bin/env python3
"""Stateful fake `gh` for agent journey contract tests.

State lives in the JSON file named by FAKE_GH_STATE so replies and resolutions
posted by the runtime are visible to its next read, like real GitHub. Every call
is appended to FAKE_GH_CALLS; unknown calls fail loudly instead of guessing.
"""

import json
import os
import sys

STATE_PATH = os.environ["FAKE_GH_STATE"]
CALLS_PATH = os.environ["FAKE_GH_CALLS"]
UNHANDLED_PATH = os.environ["FAKE_GH_UNHANDLED"]
VIEWER = "agent-login"


def load_state():
    with open(STATE_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle)


def unhandled(message):
    # Recorded separately because the runtime may absorb a failed call (for
    # example as "stack unavailable"), which would hide a gap in this fake.
    with open(UNHANDLED_PATH, "a", encoding="utf-8") as handle:
        handle.write(message + "\n")
    raise SystemExit(message)


def emit(payload, code=0):
    print(json.dumps(payload))
    raise SystemExit(code)


def flag_values(args, flag):
    values = {}
    for index, arg in enumerate(args[:-1]):
        if arg == flag and "=" in args[index + 1]:
            key, value = args[index + 1].split("=", 1)
            values[key] = value
    return values


def page(nodes):
    return {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}


def comment(row, with_body=True):
    node = {"url": row["url"], "author": {"login": row["author"]}}
    if with_body:
        node["body"] = row["body"]
    return node


def thread_node(thread):
    comments = thread["comments"]
    return {
        "id": thread["id"],
        "isResolved": thread["isResolved"],
        "isOutdated": False,
        "path": thread["path"],
        "line": thread["line"],
        "comments": page([comment(row, with_body=False) for row in comments]),
        "firstComment": {"nodes": [comment(comments[0])]},
        "latestComment": {"nodes": [comment(comments[-1])]},
    }


def pull_request_summary(state):
    return {
        "number": int(state["pr_number"]),
        "state": "OPEN",
        "isDraft": False,
        "baseRefName": "main",
        "headRefName": state["head_ref"],
        "headRefOid": state["head_sha"],
        "headRef": {"target": {"oid": state["head_sha"], "tree": {"oid": "t" + state["head_sha"][1:]}}},
        "mergeQueueEntry": None,
        "stackEntry": None,
        "stack": None,
    }


def graphql(args, state):
    query = flag_values(args, "-f").get("query", "")
    variables = flag_values(args, "-F")
    threads = {thread["id"]: thread for thread in state["threads"]}
    if "addPullRequestReviewThreadReply" in query:
        thread = threads[variables["threadId"]]
        url = f"https://github.test/reply/{variables['threadId']}/{len(thread['comments'])}"
        thread["comments"].append({"url": url, "author": VIEWER, "body": variables.get("body", "")})
        save_state(state)
        emit({"data": {"addPullRequestReviewThreadReply": {"comment": {"url": url}}}})
    if "resolveReviewThread" in query:
        thread = threads[variables["threadId"]]
        thread["isResolved"] = True
        save_state(state)
        emit({"data": {"resolveReviewThread": {"thread": {"id": thread["id"], "isResolved": True}}}})
    if "reviewThreads" in query:
        nodes = [thread_node(thread) for thread in state["threads"]]
        emit({"data": {"repository": {"pullRequest": {"reviewThreads": page(nodes)}}}})
    if "stack{" in query:
        emit({"data": {"repository": {"pullRequest": pull_request_summary(state)}}})
    unhandled(f"unhandled gh graphql query: {query[:80]}")


def rest(endpoint, state):
    prefix = f"repos/{state['repo']}/pulls/{state['pr_number']}"
    if endpoint == "user":
        emit({"login": VIEWER})
    if endpoint == prefix:
        emit(
            {
                "number": int(state["pr_number"]),
                "state": "open",
                "head": {"sha": state["head_sha"], "ref": state["head_ref"]},
                "base": {"sha": state["base_sha"], "ref": "main"},
            }
        )
    if endpoint.startswith(f"{prefix}/reviews"):
        emit([])
    if endpoint.startswith(f"{prefix}/files"):
        emit(state["files"] if endpoint.endswith("page=1") else [])
    if endpoint.startswith(f"{prefix}/commits"):
        emit([{"sha": sha} for sha in state["commits"]] if endpoint.endswith("page=1") else [])
    unhandled(f"unhandled gh api endpoint: {endpoint}")


def main():
    args = sys.argv[1:]
    with open(CALLS_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(args) + "\n")
    state = load_state()
    if args[:2] == ["auth", "status"]:
        raise SystemExit(0)
    if args[:2] == ["pr", "checks"]:
        # Mirrors real gh on a PR with no check runs: exit 1, empty stdout, message
        # on stderr (observed on RbBtSn0w/app-store-creative#8 under 3.16.0).
        if not state.get("checks"):
            kind = "required checks" if "--required" in args else "checks"
            sys.stderr.write(f"no {kind} reported on the '{state['head_ref']}' branch\n")
            raise SystemExit(1)
        emit(state["checks"])
    if args[:2] == ["api", "graphql"]:
        graphql(args, state)
    if args[:1] == ["api"]:
        rest(args[1], state)
    unhandled(f"unhandled gh args: {args}")


if __name__ == "__main__":
    main()
