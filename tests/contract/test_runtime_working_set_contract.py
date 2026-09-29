from __future__ import annotations

import json
import random
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core.runtime_store import PersistenceInvalidError, RuntimeStore


def _session() -> dict:
    return {
        "session_id": "owner/repo#123",
        "repo": "owner/repo",
        "pr_number": "123",
        "status": "WAITING_FOR_CLASSIFICATION",
        "items": {
            "finding-1": {
                "item_id": "finding-1",
                "item_kind": "local_finding",
                "state": "open",
                "status": "OPEN",
            },
            "finding-2": {
                "item_id": "finding-2",
                "item_kind": "local_finding",
                "state": "open",
                "status": "OPEN",
            },
        },
        "leases": {
            "lease-terminal": {
                "lease_id": "lease-terminal",
                "item_id": "finding-2",
                "agent_id": "old-agent",
                "role": "fixer",
                "status": "released",
            },
            "lease-active": {
                "lease_id": "lease-active",
                "item_id": "finding-1",
                "agent_id": "triage-agent",
                "role": "triage",
                "status": "active",
            },
        },
        "metadata": {},
    }


class RuntimeWorkingSetContractTest(unittest.TestCase):
    def test_bounded_read_loads_selected_item_and_all_active_leases_without_full_snapshot(self):
        from gh_address_cr.core.runtime_store import WorkingSetRequest

        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())
            request = WorkingSetRequest(item_ids=("finding-2",), include_active_leases=True)
            with patch.object(RuntimeStore, "_load_snapshot", side_effect=AssertionError("full load")):
                snapshot = store.load_working_set(request)

        self.assertEqual(set(snapshot.payload["items"]), {"finding-1", "finding-2"})
        self.assertEqual(set(snapshot.payload["leases"]), {"lease-active"})

    def test_lease_working_set_includes_owning_item(self):
        from gh_address_cr.core.runtime_store import WorkingSetRequest

        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())
            snapshot = store.load_working_set(WorkingSetRequest(lease_ids=("lease-terminal",)))

        self.assertEqual(set(snapshot.payload["leases"]), {"lease-terminal"})
        self.assertEqual(set(snapshot.payload["items"]), {"finding-2"})

    def test_bounded_transaction_loads_only_selected_item_and_active_lease(self):
        from gh_address_cr.core.runtime_store import WorkingSetRequest

        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())
            request = WorkingSetRequest(
                item_ids=("finding-1",),
                active_lease_item_ids=("finding-1",),
            )
            original = RuntimeStore._load_snapshot
            with patch.object(RuntimeStore, "_load_snapshot", autospec=True, wraps=original) as load_snapshot:
                result = store.transact_working_set(
                    request,
                    lambda payload: payload["items"]["finding-1"].update(decision="fix"),
                    operation="session_update",
                )

            self.assertEqual(load_snapshot.call_count, 0)
            self.assertEqual(set(result.payload["items"]), {"finding-1"})
            self.assertEqual(set(result.payload["leases"]), {"lease-active"})
            full = store.load().payload

        self.assertEqual(full["items"]["finding-1"]["decision"], "fix")
        self.assertNotIn("decision", full["items"]["finding-2"])
        self.assertEqual(set(full["leases"]), {"lease-active", "lease-terminal"})

    def test_bounded_transaction_does_not_advance_unrelated_row_revisions(self):
        from gh_address_cr.core.runtime_store import WorkingSetRequest

        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())
            request = WorkingSetRequest(item_ids=("finding-1",))
            store.transact_working_set(
                request,
                lambda payload: payload["items"]["finding-1"].update(decision="fix"),
                operation="session_update",
            )
            with closing(sqlite3.connect(store.database_path)) as connection:
                revisions = dict(
                    connection.execute(
                        "SELECT item_id, last_observed_revision FROM items ORDER BY item_id"
                    )
                )

        self.assertEqual(revisions, {"finding-1": 2, "finding-2": 1})

    def test_bounded_transaction_rejects_overwrite_of_unselected_existing_item(self):
        from gh_address_cr.core.runtime_store import WorkingSetRequest

        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())

            with self.assertRaises(PersistenceInvalidError) as caught:
                store.transact_working_set(
                    WorkingSetRequest(item_ids=("finding-1",)),
                    lambda payload: payload["items"].update(
                        {
                            "finding-2": {
                                "item_id": "finding-2",
                                "item_kind": "local_finding",
                                "state": "resolved",
                                "status": "RESOLVED",
                            }
                        }
                    ),
                    operation="session_update",
                )

            full = store.load().payload

        self.assertEqual(caught.exception.reason_code, "PERSISTENCE_INVALID")
        self.assertEqual(full["items"]["finding-2"]["state"], "open")

    def test_fragment_projection_is_byte_identical_to_full_projection(self):
        from gh_address_cr.core.runtime_store import WorkingSetRequest

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            store = RuntimeStore(workspace)
            store.bootstrap(_session())
            request = WorkingSetRequest(item_ids=("finding-1",))
            committed = store.transact_working_set(
                request,
                lambda payload: payload["items"]["finding-1"].update(
                    body="unicode café 雪 🚀"
                ),
                operation="session_update",
            )
            session_path = workspace / "session.json"
            ledger_path = workspace / "evidence.jsonl"
            store.materialize_compatibility_artifacts_from_rows(
                session_path=session_path,
                ledger_path=ledger_path,
                expected_revision=committed.revision,
            )
            projected = session_path.read_bytes()
            store.materialize_compatibility_artifacts(
                session_path=session_path,
                ledger_path=ledger_path,
            )
            rebuilt = session_path.read_bytes()

        self.assertEqual(projected, rebuilt)

    def test_explicit_materialization_assembles_session_from_canonical_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            store = RuntimeStore(workspace)
            store.bootstrap(_session())
            session_path = workspace / "session.json"
            ledger_path = workspace / "evidence.jsonl"

            with patch.object(
                store,
                "_load_snapshot",
                side_effect=AssertionError("explicit projection decoded the full snapshot"),
            ):
                store.materialize_compatibility_artifacts(
                    session_path=session_path,
                    ledger_path=ledger_path,
                )

            projection = json.loads(session_path.read_text(encoding="utf-8"))

        self.assertEqual(projection["items"]["finding-1"]["item_id"], "finding-1")
        self.assertEqual(projection["leases"]["lease-terminal"]["status"], "released")

    def test_bounded_lease_event_append_keeps_history_out_of_session_root(self):
        from gh_address_cr.core.runtime_store import WorkingSetRequest

        event = {
            "event_type": "lease_released",
            "timestamp": "2026-09-28T00:01:00+00:00",
            "lease_id": "lease-active",
            "item_id": "finding-1",
            "agent_id": "triage-agent",
            "role": "triage",
            "status": "released",
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())
            store.transact_working_set(
                WorkingSetRequest(lease_ids=("lease-active",)),
                lambda payload: payload["lease_events"].append(event),
                operation="lease_release",
            )
            snapshot = store.load()
            with closing(sqlite3.connect(store.database_path)) as connection:
                root = json.loads(connection.execute("SELECT payload_json FROM sessions").fetchone()[0])
                rows = [
                    json.loads(row[0])
                    for row in connection.execute("SELECT payload_json FROM lease_events ORDER BY sequence")
                ]

        self.assertNotIn("lease_events", root)
        self.assertEqual(rows, [event])
        self.assertEqual(snapshot.payload["lease_events"], [event])

    def test_randomized_bounded_mutations_match_full_projection_after_every_commit(self):
        from gh_address_cr.core.runtime_store import WorkingSetRequest

        rng = random.Random(36)
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            store = RuntimeStore(workspace)
            store.bootstrap(_session())
            session_path = workspace / "session.json"
            ledger_path = workspace / "evidence.jsonl"
            live_lease_ids: list[str] = []

            for index in range(18):
                item_id = rng.choice(("finding-1", "finding-2"))
                selected_lease_id: str | None = None
                action = index % 3
                if action == 0:
                    selected_lease_id = f"lease-random-{index}"
                    live_lease_ids.append(selected_lease_id)
                elif live_lease_ids:
                    selected_lease_id = rng.choice(live_lease_ids)

                def mutate(
                    payload,
                    *,
                    step=index,
                    lease_id=selected_lease_id,
                    lease_action=action,
                    selected_item_id=item_id,
                ):
                    payload["items"][selected_item_id]["body"] = f"step {step} 雪"
                    if lease_id and lease_action == 0:
                        payload["leases"][lease_id] = {
                            "lease_id": lease_id,
                            "item_id": selected_item_id,
                            "agent_id": "random-agent",
                            "role": "fixer",
                            "status": "released",
                        }
                    elif lease_id and lease_action == 1:
                        payload["leases"][lease_id]["reason"] = f"updated-{step}"
                    elif lease_id:
                        payload["leases"].pop(lease_id, None)
                        live_lease_ids.remove(lease_id)
                    payload["lease_events"].append(
                        {
                            "event_type": "randomized_contract_step",
                            "timestamp": f"2026-09-28T00:00:{step:02d}+00:00",
                            "lease_id": lease_id,
                            "item_id": selected_item_id,
                            "step": step,
                        }
                    )

                committed = store.transact_working_set(
                    WorkingSetRequest(
                        item_ids=(item_id,),
                        lease_ids=(selected_lease_id,) if selected_lease_id else (),
                    ),
                    mutate,
                    operation="session_update",
                )
                store.materialize_compatibility_artifacts_from_rows(
                    session_path=session_path,
                    ledger_path=ledger_path,
                    expected_revision=committed.revision,
                )
                projected = session_path.read_bytes()
                store.materialize_compatibility_artifacts(
                    session_path=session_path,
                    ledger_path=ledger_path,
                )
                self.assertEqual(projected, session_path.read_bytes(), f"step {index}")


if __name__ == "__main__":
    unittest.main()
