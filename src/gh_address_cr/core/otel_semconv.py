"""OpenTelemetry Semantic Conventions Constants.

This module re-exports pinned incubating semantic conventions constants
to avoid string literal drift across codebase instrumentation.

Pinned environment versions:
- OpenTelemetry SDK version: 1.43.0
- OpenTelemetry Semantic Conventions version: 0.64b0
"""

from opentelemetry.semconv._incubating.attributes.error_attributes import (
    ERROR_TYPE,
)
from opentelemetry.semconv._incubating.attributes.gen_ai_attributes import (
    GEN_AI_AGENT_NAME,
    GEN_AI_CONVERSATION_ID,
    GEN_AI_OPERATION_NAME,
    GEN_AI_TOOL_CALL_ARGUMENTS,
    GEN_AI_TOOL_CALL_RESULT,
    GEN_AI_TOOL_NAME,
)
from opentelemetry.semconv._incubating.attributes.process_attributes import (
    PROCESS_COMMAND_ARGS,
    PROCESS_EXECUTABLE_NAME,
    PROCESS_EXIT_CODE,
    PROCESS_PARENT_PID,
    PROCESS_PID,
)
from opentelemetry.semconv._incubating.attributes.vcs_attributes import (
    VCS_CHANGE_ID,
    VCS_CHANGE_STATE,
    VCS_PROVIDER_NAME,
    VCS_REPOSITORY_NAME,
)

GH_ADDRESS_CR_SPAN_KIND = "gh_address_cr.span.kind"
GH_ADDRESS_CR_WORKFLOW_STEP_KIND = "gh_address_cr.workflow.step.kind"
GH_ADDRESS_CR_WORKFLOW_STEP_NAME = "gh_address_cr.workflow.step.name"
GH_ADDRESS_CR_ADAPTER_SPAN_NAME = "gh_address_cr.adapter"
GH_ADDRESS_CR_COMMAND_SESSION_OPERATION_SPAN_NAME = "gh_address_cr.command_session.operation"

__all__ = [
    # Error attributes
    "ERROR_TYPE",
    # GenAI attributes
    "GEN_AI_OPERATION_NAME",
    "GEN_AI_TOOL_NAME",
    "GEN_AI_TOOL_CALL_ARGUMENTS",
    "GEN_AI_TOOL_CALL_RESULT",
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
    # gh-address-cr custom telemetry keys
    "GH_ADDRESS_CR_SPAN_KIND",
    "GH_ADDRESS_CR_WORKFLOW_STEP_KIND",
    "GH_ADDRESS_CR_WORKFLOW_STEP_NAME",
    "GH_ADDRESS_CR_ADAPTER_SPAN_NAME",
    "GH_ADDRESS_CR_COMMAND_SESSION_OPERATION_SPAN_NAME",
]
