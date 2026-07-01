from __future__ import annotations

import unittest

# Ensure all key names are imported from gh_address_cr.core.otel_semconv
from gh_address_cr.core.otel_semconv import (
    VCS_CHANGE_ID,
    VCS_CHANGE_STATE,
    VCS_PROVIDER_NAME,
    VCS_REPOSITORY_NAME,
)

# TDD: This import is expected to fail initially (ImportError)
from gh_address_cr.core.telemetry_safety import map_vcs_attributes


class TelemetrySafetyVcsTestCase(unittest.TestCase):
    def test_vcs_attributes_mapping(self) -> None:
        """T021: Test map_vcs_attributes basic mapping and validation."""
        command = "review"
        repo = "rbbtsn0w/gh-address-cr"
        pr_number = 123

        # Normal PR-scoped command mapping
        attrs = map_vcs_attributes(command, repo, pr_number)

        # 1. vcs.provider.name must be "github"
        self.assertEqual(attrs.get(VCS_PROVIDER_NAME), "github")

        # 2. vcs.change.id must be the string PR number (e.g. "123")
        self.assertEqual(attrs.get(VCS_CHANGE_ID), "123")

        # 3. vcs.repository.name must be present as a stable hash
        repo_hash = attrs.get(VCS_REPOSITORY_NAME)
        self.assertIsNotNone(repo_hash)
        # It should be a hex string of SHA-256 (64 characters)
        self.assertEqual(len(repo_hash), 64)

        # 4. Verify hash is deterministic: calling it with the same repo returns the identical hash
        attrs2 = map_vcs_attributes(command, repo, pr_number)
        self.assertEqual(attrs2.get(VCS_REPOSITORY_NAME), repo_hash)

        # 5. Verify different repo yields a different hash
        attrs_other = map_vcs_attributes(command, "other-owner/other-repo", pr_number)
        self.assertNotEqual(attrs_other.get(VCS_REPOSITORY_NAME), repo_hash)

        # 6. Verify case insensitivity: lowercase repo identifier deterministic hash
        attrs_caps = map_vcs_attributes(command, "RBBTSN0W/gh-address-cr", pr_number)
        self.assertEqual(attrs_caps.get(VCS_REPOSITORY_NAME), repo_hash)

        # 7. Verify that if repo or pr_number is missing, it returns {}
        self.assertEqual(map_vcs_attributes(command, None, pr_number), {})
        self.assertEqual(map_vcs_attributes(command, repo, None), {})
        self.assertEqual(map_vcs_attributes(command, None, None), {})

        # 8. Verify if command is not a PR-scoped session command, it returns {}
        self.assertEqual(map_vcs_attributes("version", repo, pr_number), {})
        self.assertEqual(map_vcs_attributes("doctor", repo, pr_number), {})
        self.assertEqual(map_vcs_attributes("help", repo, pr_number), {})

    def test_vcs_privacy_guarantee(self) -> None:
        """T022: Assert privacy guarantee and conditional state mapping."""
        command = "review"
        repo = "rbbtsn0w/gh-address-cr"
        pr_number = "123"

        # Scenario A: session is absent/None
        attrs_no_state = map_vcs_attributes(command, repo, pr_number)

        # 1. Assert that no plain owner name or repo name or plain URL leaks into the attributes
        for value in attrs_no_state.values():
            value_str = str(value)
            self.assertNotIn("rbbtsn0w", value_str)
            self.assertNotIn("gh-address-cr", value_str)
            self.assertNotIn("github.com", value_str)

        # 2. Assert vcs.change.state is absent when not explicitly provided
        self.assertNotIn(VCS_CHANGE_STATE, attrs_no_state)

        # Scenario B: session state is explicitly provided
        # The session may contain a status (e.g. "open", "merged")
        session_data = {"status": "open"}
        attrs_with_state = map_vcs_attributes(command, repo, pr_number, session_data)

        # 3. Assert vcs.change.state is present only if provided in session
        self.assertEqual(attrs_with_state.get(VCS_CHANGE_STATE), "open")

        # Verify that even with session provided, owner/repo/URL do not leak
        for value in attrs_with_state.values():
            value_str = str(value)
            self.assertNotIn("rbbtsn0w", value_str)
            self.assertNotIn("gh-address-cr", value_str)
            self.assertNotIn("github.com", value_str)

        # Scenario C: session has a state/status value of "merged"
        session_data_merged = {"status": "merged"}
        attrs_with_merged = map_vcs_attributes(command, repo, pr_number, session_data_merged)
        self.assertEqual(attrs_with_merged.get(VCS_CHANGE_STATE), "merged")


if __name__ == "__main__":
    unittest.main()
