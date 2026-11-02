"""Unexpected failures cannot pass a domain smoke by mentioning familiar words."""

import json
import subprocess
import sys
import unittest

from tests.installed_runtime import assert_machine_result


class InstalledRuntimeAssertionTests(unittest.TestCase):
    def test_expected_domain_error_is_accepted(self):
        payload = {"status": "FAILED", "reason_code": "SESSION_ERROR", "detail": "missing session"}
        result = subprocess.CompletedProcess([], 2, json.dumps(payload), "")
        self.assertEqual(assert_machine_result(result, exit_code=2, status="FAILED", reason_code="SESSION_ERROR"), payload)

    def test_unexpected_results_are_rejected(self):
        valid = json.dumps({"status": "FAILED", "reason_code": "SESSION_ERROR"})
        cases = (
            (99, "session migration failed irrecoverably", ""),
            (99, valid, ""),
            (2, json.dumps({"status": "FAILED", "reason_code": "SYSTEM_ERROR"}), ""),
            (2, json.dumps({"status": "READY", "reason_code": "SESSION_ERROR"}), ""),
            (2, "", ""),
            (2, "{broken", ""),
            (2, "[]", ""),
            (2, valid + "\n" + valid, ""),
            (1, "", "ModuleNotFoundError: No module named gh_address_cr"),
        )
        for code, stdout, stderr in cases:
            with self.subTest(code=code, stdout=stdout, stderr=stderr):
                result = subprocess.CompletedProcess([], code, stdout, stderr)
                with self.assertRaises(AssertionError):
                    assert_machine_result(result, exit_code=2, status="FAILED", reason_code="SESSION_ERROR")

    def test_exit_99_reproducer_is_rejected_at_the_subprocess_boundary(self):
        result = subprocess.run(
            [sys.executable, "-c", "print('session migration failed irrecoverably'); raise SystemExit(99)"],
            text=True, capture_output=True,
        )
        with self.assertRaisesRegex(AssertionError, "got 99"):
            assert_machine_result(result, exit_code=2, status="FAILED", reason_code="SESSION_ERROR")
