import unittest

from gh_address_cr.core.otel_semconv import GEN_AI_AGENT_NAME, GEN_AI_AGENT_VERSION
from gh_address_cr.core.telemetry_safety import detect_agent_session


def _identity(value: str) -> dict[str, str]:
    result = detect_agent_session({"AI_AGENT": value})
    return {key: result[key] for key in (GEN_AI_AGENT_NAME, GEN_AI_AGENT_VERSION) if key in result}


class AgentIdentityParsingTestCase(unittest.TestCase):
    def test_vercel_name_at_version_is_split(self) -> None:
        self.assertEqual(
            _identity("custom-agent@2.0"),
            {GEN_AI_AGENT_NAME: "custom-agent", GEN_AI_AGENT_VERSION: "2.0"},
        )

    def test_claude_code_underscore_format_is_split(self) -> None:
        self.assertEqual(
            _identity("claude-code_2-1-293_agent"),
            {GEN_AI_AGENT_NAME: "claude-code", GEN_AI_AGENT_VERSION: "2.1.293"},
        )

    def test_bare_name_has_no_version(self) -> None:
        self.assertEqual(_identity("claude-cli"), {GEN_AI_AGENT_NAME: "claude-cli"})

    def test_same_agent_different_versions_share_one_name(self) -> None:
        names = {_identity(f"claude-code_2-1-{patch}_agent")[GEN_AI_AGENT_NAME] for patch in (270, 286, 293)}
        self.assertEqual(names, {"claude-code"})

    def test_surrounding_whitespace_is_stripped(self) -> None:
        self.assertEqual(_identity("  codex@0.5.1 "), {GEN_AI_AGENT_NAME: "codex", GEN_AI_AGENT_VERSION: "0.5.1"})

    def test_invalid_version_keeps_name_and_drops_version(self) -> None:
        self.assertEqual(_identity("codex@not a version"), {GEN_AI_AGENT_NAME: "codex"})

    def test_invalid_name_drops_the_whole_identity(self) -> None:
        for value in ("@1.0", "", "   ", "two words@1.0", "x" * 65, "a/b", "agent\nname"):
            with self.subTest(value=value):
                self.assertEqual(_identity(value), {})

    def test_overlong_version_is_dropped(self) -> None:
        self.assertEqual(_identity("codex@" + "1" * 65), {GEN_AI_AGENT_NAME: "codex"})

    def test_unsafe_values_are_dropped_not_raised(self) -> None:
        for value in ("/Users/someone/agent", "token=abc123", "ghp_abcdefghijklmnopqrstuvwxyz0123456789"):
            with self.subTest(value=value):
                self.assertEqual(_identity(value), {})

    def test_absent_ai_agent_emits_nothing(self) -> None:
        result = detect_agent_session({})
        self.assertNotIn(GEN_AI_AGENT_NAME, result)
        self.assertNotIn(GEN_AI_AGENT_VERSION, result)


if __name__ == "__main__":
    unittest.main()
