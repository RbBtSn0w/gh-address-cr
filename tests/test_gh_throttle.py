"""Spec 045: advisory machine-local `gh` throttle."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core.process_lock import try_acquire_execution_lock
from gh_address_cr.github import throttle
from gh_address_cr.github.client import GitHubClient
from gh_address_cr.github.errors import GitHubRateLimitError

MUTATION_CMD = ["gh", "api", "graphql", "-f", "query=mutation($t:ID!){ x }", "-F", "t=1"]
READ_CMD = ["gh", "api", "graphql", "-f", "query=query { viewer { login } }"]


class ThrottleTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        env = patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.root = self.state / throttle.THROTTLE_DIRECTORY


class DetectionTests(unittest.TestCase):
    def test_mutations_are_detected_from_the_graphql_query_argument(self) -> None:
        self.assertTrue(throttle.is_mutation_command(MUTATION_CMD))
        self.assertFalse(throttle.is_mutation_command(READ_CMD))
        self.assertFalse(throttle.is_mutation_command(["gh", "api", "user"]))

    def test_rate_limit_signals(self) -> None:
        self.assertTrue(throttle.is_rate_limit_result("rate_limit", 1, ""))
        self.assertFalse(throttle.is_rate_limit_result("network", 1, ""))
        graphql = json.dumps({"errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]})
        self.assertTrue(throttle.is_rate_limit_result(None, 0, graphql))

    def test_a_comment_mentioning_the_word_is_not_a_rate_limit_signal(self) -> None:
        body = json.dumps({"data": {"body": 'the "type": "RATE_LIMITED" case is handled'}})
        self.assertFalse(throttle.is_rate_limit_result(None, 0, body))


class BackoffTests(ThrottleTestCase):
    def test_open_backoff_fails_fast_without_running_the_command(self) -> None:
        throttle.record_rate_limit()
        ran = []
        with self.assertRaises(GitHubRateLimitError):
            with throttle.gh_call_gate(READ_CMD):
                ran.append(True)
        self.assertEqual(ran, [])

    def test_expired_backoff_is_ignored(self) -> None:
        self.root.mkdir(parents=True)
        (self.root / "backoff-until.json").write_text(json.dumps({"until": time.time() - 1}))
        with throttle.gh_call_gate(READ_CMD):
            pass

    def test_malformed_backoff_file_is_ignored(self) -> None:
        self.root.mkdir(parents=True)
        for content in ("not json", "[]", json.dumps({"until": "soon"}), json.dumps({"until": True})):
            with self.subTest(content=content):
                (self.root / "backoff-until.json").write_text(content)
                with throttle.gh_call_gate(READ_CMD):
                    pass

    def test_a_later_signal_never_shortens_the_window(self) -> None:
        self.root.mkdir(parents=True)
        far = time.time() + 3600
        (self.root / "backoff-until.json").write_text(json.dumps({"until": far}))
        throttle.record_rate_limit()
        self.assertEqual(json.loads((self.root / "backoff-until.json").read_text())["until"], far)


class FailOpenTests(unittest.TestCase):
    def test_unwritable_state_dir_does_not_block_the_call(self) -> None:
        with tempfile.NamedTemporaryFile() as blocker, patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": blocker.name}):
            with throttle.gh_call_gate(MUTATION_CMD):
                pass
            throttle.record_rate_limit()


class SlotTests(ThrottleTestCase):
    def test_exhausted_slots_time_out_and_proceed(self) -> None:
        self.root.mkdir(parents=True)
        held = [try_acquire_execution_lock(self.root, f"slot-{i}") for i in range(throttle.READ_SLOTS)]
        self.addCleanup(lambda: [lock.release() for lock in held if lock])
        ran = []
        with (
            patch.object(throttle, "SLOT_WAIT_SECONDS", 0.2),
            patch("gh_address_cr.otel_tracing.add_current_span_event") as event,
        ):
            with throttle.gh_call_gate(READ_CMD):
                ran.append(True)
        self.assertEqual(ran, [True])
        wait = [c for c in event.call_args_list if c.args[0] == "gh_address_cr.github.throttle.wait"][0]
        self.assertIs(wait.args[1]["gh_address_cr.github.throttle.timed_out"], True)
        self.assertEqual(wait.args[1]["gh_address_cr.github.throttle.kind"], "read")

    def test_slot_is_released_after_the_call(self) -> None:
        with throttle.gh_call_gate(READ_CMD):
            pass
        lock = try_acquire_execution_lock(self.root, "slot-0")
        self.assertIsNotNone(lock)
        lock.release()


class MutationLaneTests(ThrottleTestCase):
    def test_mutations_are_spaced_by_the_documented_gap(self) -> None:
        with patch("gh_address_cr.github.throttle.time.sleep") as sleep:
            with throttle.gh_call_gate(MUTATION_CMD):
                pass
            with throttle.gh_call_gate(MUTATION_CMD):
                pass
        waited = [call.args[0] for call in sleep.call_args_list]
        self.assertEqual(len(waited), 1)
        self.assertGreater(waited[0], 0)
        self.assertLessEqual(waited[0], throttle.MUTATION_SPACING_SECONDS)

    def test_reads_do_not_wait_for_mutation_spacing(self) -> None:
        with throttle.gh_call_gate(MUTATION_CMD):
            pass
        with patch("gh_address_cr.github.throttle.time.sleep") as sleep:
            with throttle.gh_call_gate(READ_CMD):
                pass
        sleep.assert_not_called()

    def test_mutation_lane_is_exclusive(self) -> None:
        self.root.mkdir(parents=True)
        lane = try_acquire_execution_lock(self.root, "mutation")
        self.addCleanup(lane.release)
        with patch.object(throttle, "MUTATION_WAIT_SECONDS", 0.2), patch(
            "gh_address_cr.otel_tracing.add_current_span_event"
        ) as event:
            with throttle.gh_call_gate(MUTATION_CMD):
                pass
        wait = [c for c in event.call_args_list if c.args[0] == "gh_address_cr.github.throttle.wait"][0]
        self.assertIs(wait.args[1]["gh_address_cr.github.throttle.timed_out"], True)


class DefaultRunnerTests(ThrottleTestCase):
    def test_rate_limited_result_opens_the_breaker_for_later_calls(self) -> None:
        limited = subprocess.CompletedProcess(READ_CMD, 1, "", "gh: API rate limit exceeded (HTTP 403)")
        with patch("gh_address_cr.core.command_runner.run_cmd", return_value=limited) as run_cmd:
            GitHubClient._default_runner(READ_CMD)
            with self.assertRaises(GitHubRateLimitError):
                GitHubClient._default_runner(READ_CMD)
        run_cmd.assert_called_once()

    def test_healthy_result_leaves_no_backoff(self) -> None:
        ok = subprocess.CompletedProcess(READ_CMD, 0, json.dumps({"data": {}}), "")
        with patch("gh_address_cr.core.command_runner.run_cmd", return_value=ok):
            GitHubClient._default_runner(READ_CMD)
        self.assertFalse((self.root / "backoff-until.json").exists())


if __name__ == "__main__":
    unittest.main()
