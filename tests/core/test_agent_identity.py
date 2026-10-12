import unittest

from gh_address_cr.core.otel_semconv import (
    GEN_AI_AGENT_NAME,
    GEN_AI_AGENT_VERSION,
    GEN_AI_CONVERSATION_ID,
)
from gh_address_cr.core.telemetry_safety import detect_agent_session

_IDENTITY_KEYS = (GEN_AI_AGENT_NAME, GEN_AI_AGENT_VERSION)


def _detect(value: str) -> dict[str, str]:
    return detect_agent_session({"AI_AGENT": value})


def _identity(value: str) -> dict[str, str]:
    result = _detect(value)
    return {key: result[key] for key in _IDENTITY_KEYS if key in result}


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

    def test_claude_code_prerelease_suffix_stays_out_of_the_name(self) -> None:
        self.assertEqual(
            _identity("claude-code_2-1-293-beta_agent"),
            {GEN_AI_AGENT_NAME: "claude-code", GEN_AI_AGENT_VERSION: "2.1.293-beta"},
        )

    def test_bare_name_has_no_version(self) -> None:
        self.assertEqual(_identity("claude-cli"), {GEN_AI_AGENT_NAME: "claude-cli"})

    def test_shapes_are_parsed_without_knowing_any_vendor(self) -> None:
        # Pins "parse by shape, never by vendor name": an unseen product is handled
        # exactly like a known one, so no vendor table can hide in the parser.
        for product in ("claude-code", "codex", "kimi-cli", "some-future-agent"):
            with self.subTest(product=product):
                self.assertEqual(
                    _identity(f"{product}_1-2-3_agent"),
                    {GEN_AI_AGENT_NAME: product, GEN_AI_AGENT_VERSION: "1.2.3"},
                )
                self.assertEqual(
                    _identity(f"{product}@1.2.3"),
                    {GEN_AI_AGENT_NAME: product, GEN_AI_AGENT_VERSION: "1.2.3"},
                )

    def test_same_agent_different_versions_share_one_name(self) -> None:
        names = {_identity(f"claude-code_2-1-{patch}_agent")[GEN_AI_AGENT_NAME] for patch in (270, 286, 293)}
        self.assertEqual(names, {"claude-code"})

    def test_name_case_is_normalised_so_variants_share_one_name(self) -> None:
        for value in ("Claude-Code@1.0", "CLAUDE-CODE@1.0", "claude-code@1.0"):
            with self.subTest(value=value):
                self.assertEqual(
                    _identity(value),
                    {GEN_AI_AGENT_NAME: "claude-code", GEN_AI_AGENT_VERSION: "1.0"},
                )

    def test_surrounding_whitespace_is_stripped(self) -> None:
        self.assertEqual(_identity("  codex@0.5.1 "), {GEN_AI_AGENT_NAME: "codex", GEN_AI_AGENT_VERSION: "0.5.1"})

    def test_version_may_carry_dots_underscores_and_prerelease_marks(self) -> None:
        for version in ("1.2.3.4", "2.0.0-rc.1", "0_5"):
            with self.subTest(version=version):
                self.assertEqual(_identity(f"codex@{version}"), {GEN_AI_AGENT_NAME: "codex", GEN_AI_AGENT_VERSION: version})

    def test_invalid_version_keeps_name_and_drops_version(self) -> None:
        self.assertEqual(_identity("codex@not a version"), {GEN_AI_AGENT_NAME: "codex"})
        self.assertEqual(_identity("codex@"), {GEN_AI_AGENT_NAME: "codex"})
        self.assertEqual(_identity("codex@1.0@x"), {GEN_AI_AGENT_NAME: "codex"})

    def test_invalid_name_drops_the_whole_identity(self) -> None:
        for value in ("@1.0", "two words@1.0", "x" * 65, "a/b", "agent\nname", "-agent@1"):
            with self.subTest(value=value):
                self.assertEqual(_identity(value), {})

    def test_underscore_names_are_not_accepted_as_bare_names(self) -> None:
        # A versioned shape the Claude Code parser does not recognise must be rejected,
        # never emitted whole: that would put the version back into gen_ai.agent.name.
        for value in ("claude-code_2-1-293_agent_extra", "my_agent_2-1_agent", "codex_cli"):
            with self.subTest(value=value):
                self.assertEqual(_identity(value), {})

    def test_overlong_version_is_dropped(self) -> None:
        self.assertEqual(_identity("codex@" + "1" * 65), {GEN_AI_AGENT_NAME: "codex"})

    def test_unsafe_values_are_dropped_not_raised(self) -> None:
        for value in ("/Users/someone/agent", "token=abc123", "ghp_abcdefghijklmnopqrstuvwxyz0123456789"):
            with self.subTest(value=value):
                self.assertEqual(_identity(value), {})

    def test_token_marker_in_a_well_formed_version_is_dropped(self) -> None:
        # Passes the version label pattern, so only the token-marker check can reject it.
        self.assertEqual(_identity("codex@ghp_abcdefghijklmnopqrstuvwxyz0123456789"), {GEN_AI_AGENT_NAME: "codex"})

    def test_absent_ai_agent_emits_nothing(self) -> None:
        self.assertEqual(detect_agent_session({}), {})

    def test_rejected_value_is_never_recorded(self) -> None:
        for value in ("token=abc123", "Kimi K2@1.0"):
            with self.subTest(value=value):
                self.assertEqual(_detect(value), {})

    def test_blank_ai_agent_counts_as_absent(self) -> None:
        for value in ("", "   "):
            with self.subTest(value=value):
                self.assertEqual(_detect(value), {})


class AgentIdentityDoesNotDisturbSessionCorrelationTestCase(unittest.TestCase):
    def test_invalid_ai_agent_keeps_the_conversation_id(self) -> None:
        result = detect_agent_session({"GH_ADDRESS_CR_CONVERSATION_ID": "session-1", "AI_AGENT": "Kimi K2@1.0"})
        self.assertEqual(result[GEN_AI_CONVERSATION_ID], "session-1")
        self.assertEqual(result["gen_ai.conversation.id.source"], "GH_ADDRESS_CR_CONVERSATION_ID")
        self.assertNotIn(GEN_AI_AGENT_NAME, result)

    def test_valid_ai_agent_and_conversation_id_are_both_emitted(self) -> None:
        result = detect_agent_session({"CLAUDE_CODE_SESSION_ID": "session-2", "AI_AGENT": "claude-code_2-1-293_agent"})
        self.assertEqual(result[GEN_AI_CONVERSATION_ID], "session-2")
        self.assertEqual(result[GEN_AI_AGENT_NAME], "claude-code")
        self.assertEqual(result[GEN_AI_AGENT_VERSION], "2.1.293")


if __name__ == "__main__":
    unittest.main()
