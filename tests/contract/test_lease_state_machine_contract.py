"""Executable form of specs/033-lease-state-machine/contracts/.

The expected values are read from the markdown tables, not copied into this file, so the
document and the test cannot drift apart: changing either without the other fails here.

Three checks:

- the 24-cell transition table (`lease-transitions.md`, Table 1);
- the claim table (Table 2);
- the entry-point inventory (`lease-entry-points.md`), compared in both directions with
  what an AST scan of `src/` actually finds.

The inventory is the one that earns its keep. The defects fixed under #273 were each found
at an entry point nobody had listed, and a hand-written list missed `reclaim_lease` on the
first attempt. A scan cannot.
"""

from __future__ import annotations

import ast
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gh_address_cr.core import leases as L

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "specs" / "033-lease-state-machine" / "contracts"
SRC = ROOT / "src" / "gh_address_cr"
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
STATUSES = ("active", "submitted", "accepted", "rejected", "expired", "released")


def _table(markdown: str, heading: str) -> list[list[str]]:
    """The rows of the first markdown table after `heading`, header row excluded."""
    section = markdown.split(heading, 1)[1]
    rows = []
    for line in section.splitlines():
        if line.startswith("|"):
            cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            rows.append(cells)
        elif rows:
            break
    return rows[1:]


def _called_name(call: ast.Call) -> str | None:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)


def _cell(text: str) -> str:
    """A table cell as a plain value: the `(no-op)` annotation and the backticks removed.

    The backticks wrap the value and the annotation follows them, so stripping only the
    ends of the raw cell leaves a stray backtick behind.
    """
    return re.sub(r"\s*\(no-op\)\s*$", "", text).replace("`", "").strip()


def _lease_session(status: str, *, ttl: int = 3600):
    item = {"item_id": "it", "item_kind": "local_finding", "state": "claimed", "conflict_keys": []}
    session = {"items": {"it": item}, "leases": {}, "lease_events": []}
    L.claim_lease(session, item, agent_id="a", role="fixer", request_hash="h", lease_id="L0", now=NOW, ttl_seconds=ttl)
    if status != "active":
        L._set(session["leases"]["L0"], "status", status)
    return session, item


class TransitionTableTest(unittest.TestCase):
    OPERATIONS = {
        "submit": lambda s: L.submit_lease(
            s, "L0", agent_id="a", role="fixer", item_id="it", request_hash="h", now=NOW + timedelta(seconds=1)
        ),
        "accept": lambda s: L.accept_lease(s, "L0", now=NOW + timedelta(seconds=1)),
        "release": lambda s: L.release_lease(s, "L0", now=NOW + timedelta(seconds=1), reason="r"),
        "expire (TTL passed)": lambda s: L.expire_leases(s, now=NOW + timedelta(hours=2)),
    }

    def _observed(self, status: str, operation: str) -> str:
        session, _ = _lease_session(status)
        try:
            self.OPERATIONS[operation](session)
        except L.LeaseSubmissionError as error:
            return error.reason_code
        return L._get(session["leases"]["L0"], "status")

    def test_every_cell_of_the_transition_table_matches_the_contract(self):
        rows = _table((CONTRACTS / "lease-transitions.md").read_text(encoding="utf-8"), "## Table 1: transitions")
        operations = list(self.OPERATIONS)

        self.assertEqual([row[0] for row in rows], list(STATUSES), "the table must list every status, in order")
        for row in rows:
            self.assertEqual(len(row) - 1, len(operations))
            for operation, expected in zip(operations, row[1:], strict=True):
                with self.subTest(status=row[0], operation=operation):
                    self.assertEqual(self._observed(row[0], operation), _cell(expected))

    def test_the_status_sets_match_the_contract(self):
        self.assertEqual(set(L.ACTIVE_LEASE_STATUSES), {"active", "submitted"})
        self.assertEqual(set(L.TERMINAL_LEASE_STATUSES), {"accepted", "rejected", "expired", "released"})
        self.assertEqual(set(L.ACTIVE_LEASE_STATUSES) | set(L.TERMINAL_LEASE_STATUSES), set(STATUSES))


class ClaimTableTest(unittest.TestCase):
    CLAIMANTS = (("a", "fixer"), ("b", "fixer"), ("b", "verifier"))

    def test_every_cell_of_the_claim_table_matches_the_contract(self):
        rows = _table((CONTRACTS / "lease-transitions.md").read_text(encoding="utf-8"), "## Table 2: claim")

        self.assertEqual([row[0] for row in rows], list(STATUSES))
        for row in rows:
            for (agent, role), expected in zip(self.CLAIMANTS, row[1:], strict=True):
                with self.subTest(existing=row[0], claimant=f"{agent}/{role}"):
                    session, item = _lease_session(row[0])
                    try:
                        L.claim_lease(
                            session,
                            item,
                            agent_id=agent,
                            role=role,
                            request_hash="h2",
                            lease_id="L1",
                            now=NOW + timedelta(seconds=1),
                        )
                        observed = "new lease"
                    except L.LeaseConflictError as error:
                        observed = error.reason_code
                    self.assertEqual(observed, expected)

    def test_claim_expires_a_lease_past_its_ttl_before_checking(self):
        session, item = _lease_session("active", ttl=1)

        L.claim_lease(
            session, item, agent_id="b", role="fixer", request_hash="h2", lease_id="L1", now=NOW + timedelta(hours=2)
        )

        self.assertEqual(L._get(session["leases"]["L0"], "status"), "expired")


class SubmittedIsTransientTest(unittest.TestCase):
    """No lease is ever at rest in `submitted` (spec 033 FR-008).

    `submit_lease` is called only where the very next statement is `accept_lease` on the
    same lease, so nothing can fail or be saved in between. The transition table still has
    a `submitted` row, but a session on disk never contains one; "evidence sent but not yet
    accepted" is not a state this runtime has. If a later change splits the two calls, a
    submitted lease becomes observable and can expire, and this test is where that decision
    has to be made visibly.
    """

    def test_every_submit_is_immediately_followed_by_an_accept_of_the_same_lease(self):
        sites = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for block_owner in ast.walk(tree):
                for field in ("body", "orelse", "finalbody"):
                    block = getattr(block_owner, field, None)
                    if not isinstance(block, list):
                        continue
                    for index, statement in enumerate(block):
                        call = getattr(statement, "value", None)
                        if not (isinstance(call, ast.Call) and _called_name(call) == "submit_lease"):
                            continue
                        following = block[index + 1] if index + 1 < len(block) else None
                        next_call = getattr(following, "value", None)
                        sites.append(
                            (
                                f"{path.relative_to(SRC)}:{statement.lineno}",
                                isinstance(next_call, ast.Call)
                                and _called_name(next_call) == "accept_lease"
                                and ast.dump(next_call.args[1]) == ast.dump(call.args[1]),
                            )
                        )

        self.assertTrue(sites, "no submit_lease call found; the scan is broken")
        self.assertEqual([site for site, paired in sites if not paired], [])

    def test_a_submission_leaves_no_lease_in_submitted(self):
        # Accepted and rejected outcomes alike: nothing persists in the in-between state.
        import json
        import os
        import tempfile
        from unittest.mock import patch

        from gh_address_cr.core import agent_protocol
        from gh_address_cr.core.errors import WorkflowError
        from gh_address_cr.core.session import SessionManager
        from tests.test_control_plane_workflow import github_thread

        for agent_in_response in ("fixer-1", "someone-else"):
            with self.subTest(response_agent=agent_in_response):
                with tempfile.TemporaryDirectory() as tmp:
                    with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                        manager = SessionManager("owner/repo", "910")
                        session = manager.create(status="WAITING_FOR_FIX")
                        item = github_thread("github-thread:S")
                        session["items"] = {item["item_id"]: item}
                        manager.save(session)
                        agent_protocol.record_classification(
                            "owner/repo",
                            "910",
                            item_id=item["item_id"],
                            classification="clarify",
                            agent_id="fixer-1",
                            note="n",
                        )
                        claimed = agent_protocol.issue_action_request(
                            "owner/repo", "910", role="fixer", agent_id="fixer-1", item_id=item["item_id"]
                        )
                        request = json.loads(Path(claimed["request_path"]).read_text(encoding="utf-8"))
                        response_path = Path(tmp) / "response.json"
                        response_path.write_text(
                            json.dumps(
                                {
                                    "schema_version": request["schema_version"],
                                    "request_id": request["request_id"],
                                    "lease_id": request["lease_id"],
                                    "agent_id": agent_in_response,
                                    "item_id": item["item_id"],
                                    "resolution": "clarify",
                                    "note": "Not a defect; declining with rationale.",
                                    "reply_markdown": "Not a defect; declining with rationale.",
                                }
                            ),
                            encoding="utf-8",
                        )
                        try:
                            agent_protocol.submit_action_response("owner/repo", "910", response_path=response_path)
                        except WorkflowError:
                            pass

                        statuses = {lease["status"] for lease in manager.load()["leases"].values()}
                        self.assertNotIn("submitted", statuses)


class SessionLeasesShapeTest(unittest.TestCase):
    """The rollbacks read `load_session(...).get("leases", {})` and iterate it.

    That is only safe because `load_session` normalizes a non-dict `leases` (an explicit
    `null`, a list) to `{}`. The rollback code does not add its own `or {}` guard, since
    that branch could never run; this test is what makes relying on the normalization
    safe instead of assumed.
    """

    def test_load_session_returns_a_dict_for_any_malformed_leases_value(self):
        import json
        import os
        import tempfile
        from unittest.mock import patch

        from gh_address_cr.core import session as session_store
        from gh_address_cr.core.session import SessionManager

        for malformed in (None, [], "oops", 0):
            with self.subTest(leases=malformed):
                with tempfile.TemporaryDirectory() as tmp:
                    with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                        SessionManager("owner/repo", "900").save(
                            SessionManager("owner/repo", "900").create(status="WAITING_FOR_FIX")
                        )
                        path = next(Path(tmp).rglob("session.json"))
                        raw = json.loads(path.read_text(encoding="utf-8"))
                        raw["leases"] = malformed
                        path.write_text(json.dumps(raw), encoding="utf-8")

                        self.assertEqual(session_store.load_session("owner/repo", "900")["leases"], {})


class EntryPointInventoryTest(unittest.TestCase):
    """Every lease-creating call site under src/ is in the inventory, and only those."""

    # `_lease_new_github_thread` is included because the batch path mints its leases
    # through it rather than through `issue_action_request`; without it the batch entry
    # point, `issue_batch_action_request`, would be invisible to the scan and would have
    # to be exempted by hand, which is the kind of gap this test exists to close.
    CREATING_CALLS = {
        "issue_action_request",
        "claimed_fixer_lease",
        "claim_lease",
        "grant_lease",
        "_lease_new_github_thread",
    }

    @staticmethod
    def _enclosing_function(node, parents) -> str:
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
        return "<module>"

    def _scan(self) -> set[tuple[str, str]]:
        found = set()
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name in self.CREATING_CALLS:
                    found.add((str(path.relative_to(SRC)), self._enclosing_function(node, parents)))
        return found

    def _declared(self) -> dict[tuple[str, str], tuple[str, str]]:
        rows = _table((CONTRACTS / "lease-entry-points.md").read_text(encoding="utf-8"), "## Entry points")
        return {(row[0], row[1]): (row[2], row[3]) for row in rows}

    def test_every_lease_creating_call_site_is_listed_and_every_listing_exists(self):
        found = self._scan()
        declared = set(self._declared())

        self.assertEqual(
            found - declared,
            set(),
            "call sites that create leases but are not in lease-entry-points.md: add a row with a class",
        )
        self.assertEqual(
            declared - found,
            set(),
            "rows in lease-entry-points.md for functions that no longer call a lease-creating primitive",
        )

    def test_no_one_shot_or_orchestrated_row_is_marked_unprotected(self):
        # FR-001. A row that admits it violates the rule cannot be merged: the fix and its
        # row change land together.
        unprotected = [
            entry
            for entry, (kind, protection) in self._declared().items()
            if kind in {"one-shot", "orchestrated"} and "Not protected" in protection
        ]
        self.assertEqual(unprotected, [], "one-shot/orchestrated entry points that violate FR-001")


if __name__ == "__main__":
    unittest.main()
