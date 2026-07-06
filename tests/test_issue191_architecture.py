from __future__ import annotations

import unittest


class Issue191ArchitectureTestCase(unittest.TestCase):
    def test_telemetry_adapters_live_in_a_dedicated_module(self):
        from gh_address_cr.core import telemetry

        self.assertEqual(telemetry.GenericAgentJsonlAdapter.__module__, "gh_address_cr.core.telemetry_adapters")
        self.assertEqual(telemetry.CodexHostJsonAdapter.__module__, "gh_address_cr.core.telemetry_adapters")

    def test_session_telemetry_runtime_lives_in_a_dedicated_module(self):
        from gh_address_cr.core import telemetry

        self.assertEqual(telemetry.SessionTelemetry.__module__, "gh_address_cr.core.telemetry_runtime")

    def test_transient_github_failures_use_one_shared_marker_source(self):
        from gh_address_cr.core.command_runner import is_transient_gh_failure
        from gh_address_cr.github.client import _is_transient
        from gh_address_cr.github.diagnostics import classify_github_failure

        stderr = "error connecting to github graphql failed with 502"

        self.assertTrue(is_transient_gh_failure(stderr=stderr))
        self.assertTrue(_is_transient(stderr, ""))
        self.assertEqual(classify_github_failure(stderr)["stderr_category"], "network")


if __name__ == "__main__":
    unittest.main()
