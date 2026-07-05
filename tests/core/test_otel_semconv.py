import unittest

from gh_address_cr.core import otel_semconv


class TestOtelSemconv(unittest.TestCase):
    def test_otel_semconv_exports(self):
        # Verify all expected constants are present in __all__ and as attributes
        expected = [
            # Error attributes
            "ERROR_TYPE",
            # GenAI attributes
            "GEN_AI_OPERATION_NAME",
            "GEN_AI_TOOL_NAME",
            "GEN_AI_TOOL_CALL_ARGUMENTS",
            "GEN_AI_CONVERSATION_ID",
            "GEN_AI_AGENT_NAME",
            # Process attributes
            "PROCESS_EXECUTABLE_NAME",
            "PROCESS_PID",
            "PROCESS_EXIT_CODE",
            "PROCESS_COMMAND_ARGS",
            "PROCESS_PARENT_PID",
            # VCS attributes
            "VCS_CHANGE_ID",
            "VCS_PROVIDER_NAME",
            "VCS_REPOSITORY_NAME",
            "VCS_CHANGE_STATE",
            "GH_ADDRESS_CR_CLI_INIT_SPAN_NAME",
            "GH_ADDRESS_CR_SUBPROCESS_SPAN_NAME",
        ]
        for name in expected:
            with self.subTest(name=name):
                self.assertTrue(hasattr(otel_semconv, name), f"{name} is missing from otel_semconv")
                self.assertIn(name, otel_semconv.__all__, f"{name} is missing from __all__")
                value = getattr(otel_semconv, name)
                self.assertIsInstance(value, str, f"{name} must be a string")
                self.assertTrue(len(value) > 0, f"{name} value cannot be empty")


if __name__ == "__main__":
    unittest.main()
