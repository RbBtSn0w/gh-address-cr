"""OpenTelemetry Semantic Conventions Constants.

This module re-exports pinned incubating semantic conventions constants
to avoid string literal drift across codebase instrumentation.

Minimum supported versions (declared in pyproject.toml):
- opentelemetry-sdk 1.40.0, which pins opentelemetry-semantic-conventions 0.61b0. That is
  the first release defining every constant imported below; GEN_AI_AGENT_VERSION is the
  newest of them (GEN_AI_TOOL_CALL_ARGUMENTS/RESULT arrived in 0.60b0).
- The sdk pins semantic-conventions exactly, so the sdk floor is the only lever on these
  `_incubating` imports. Importing a constant that an older release lacks makes every CLI
  command fail at import time, so raise the floor in the same change that adds an import.
  The otel-minimum-versions CI job installs the declared floors, checks that exactly those
  versions are installed, and runs the tests (scripts/otel_min_constraints.py).
"""

from opentelemetry.semconv._incubating.attributes.error_attributes import (
    ERROR_TYPE,
)
from opentelemetry.semconv._incubating.attributes.gen_ai_attributes import (
    GEN_AI_AGENT_NAME,
    GEN_AI_AGENT_VERSION,
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
# The previous invocation's exit-time export wait (Spec 041 record). The current
# invocation's own wait happens after its span ends and cannot be reported on it.
GH_ADDRESS_CR_TELEMETRY_PREVIOUS_SHUTDOWN_WAIT_MS = "gh_address_cr.telemetry.previous_shutdown_wait_ms"
GH_ADDRESS_CR_TELEMETRY_PREVIOUS_SHUTDOWN_TIMED_OUT = "gh_address_cr.telemetry.previous_shutdown_timed_out"
# Bounded enum: command | help | version | usage_error (see docs/rfcs/043-telemetry-invocation-kind).
GH_ADDRESS_CR_INVOCATION_KIND = "gh_address_cr.invocation.kind"
GH_ADDRESS_CR_WORKFLOW_STEP_KIND = "gh_address_cr.workflow.step.kind"
GH_ADDRESS_CR_WORKFLOW_STEP_NAME = "gh_address_cr.workflow.step.name"
GH_ADDRESS_CR_ADAPTER_SPAN_NAME = "gh_address_cr.adapter"
GH_ADDRESS_CR_CLI_INIT_SPAN_NAME = "gh_address_cr.cli.init"
GH_ADDRESS_CR_COMMAND_SESSION_OPERATION_SPAN_NAME = "gh_address_cr.command_session.operation"
GH_ADDRESS_CR_SUBPROCESS_SPAN_NAME = "gh_address_cr.subprocess"
ERROR_CATEGORY = "error.category"
ERROR_EXPECTED = "error.expected"

__all__ = [
    # Error attributes
    "ERROR_TYPE",
    "ERROR_CATEGORY",
    "ERROR_EXPECTED",
    # GenAI attributes
    "GEN_AI_OPERATION_NAME",
    "GEN_AI_TOOL_NAME",
    "GEN_AI_TOOL_CALL_ARGUMENTS",
    "GEN_AI_TOOL_CALL_RESULT",
    "GEN_AI_CONVERSATION_ID",
    "GEN_AI_AGENT_NAME",
    "GEN_AI_AGENT_VERSION",
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
    "GH_ADDRESS_CR_CLI_INIT_SPAN_NAME",
    "GH_ADDRESS_CR_COMMAND_SESSION_OPERATION_SPAN_NAME",
    "GH_ADDRESS_CR_SUBPROCESS_SPAN_NAME",
]
