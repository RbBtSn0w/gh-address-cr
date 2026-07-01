import unittest

from gh_address_cr.core.otel_semconv import (
    ERROR_TYPE,
    GEN_AI_AGENT_NAME,
    GEN_AI_CONVERSATION_ID,
    GEN_AI_OPERATION_NAME,
    GEN_AI_TOOL_CALL_ARGUMENTS,
    GEN_AI_TOOL_CALL_RESULT,
    GEN_AI_TOOL_NAME,
    PROCESS_COMMAND_ARGS,
    PROCESS_EXECUTABLE_NAME,
    PROCESS_EXIT_CODE,
    PROCESS_PARENT_PID,
    PROCESS_PID,
    VCS_CHANGE_ID,
    VCS_CHANGE_STATE,
    VCS_PROVIDER_NAME,
    VCS_REPOSITORY_NAME,
)


class OtelSemconvPinsTestCase(unittest.TestCase):
    def test_otel_semconv_pins(self):
        """Test Otel Semantic Convention constant pin values."""
        self.assertEqual(PROCESS_EXECUTABLE_NAME, "process.executable.name")
        self.assertEqual(PROCESS_PID, "process.pid")
        self.assertEqual(PROCESS_EXIT_CODE, "process.exit.code")
        self.assertEqual(PROCESS_COMMAND_ARGS, "process.command_args")
        self.assertEqual(PROCESS_PARENT_PID, "process.parent_pid")
        self.assertEqual(GEN_AI_OPERATION_NAME, "gen_ai.operation.name")
        self.assertEqual(GEN_AI_TOOL_NAME, "gen_ai.tool.name")
        self.assertEqual(GEN_AI_TOOL_CALL_ARGUMENTS, "gen_ai.tool.call.arguments")
        self.assertEqual(GEN_AI_TOOL_CALL_RESULT, "gen_ai.tool.call.result")
        self.assertEqual(GEN_AI_CONVERSATION_ID, "gen_ai.conversation.id")
        self.assertEqual(GEN_AI_AGENT_NAME, "gen_ai.agent.name")
        self.assertEqual(VCS_CHANGE_ID, "vcs.change.id")
        self.assertEqual(VCS_PROVIDER_NAME, "vcs.provider.name")
        self.assertEqual(VCS_REPOSITORY_NAME, "vcs.repository.name")
        self.assertEqual(VCS_CHANGE_STATE, "vcs.change.state")
        self.assertEqual(ERROR_TYPE, "error.type")
