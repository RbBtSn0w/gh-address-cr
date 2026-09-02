"""Reason-code remediation carried inline on error summaries.

`status-action-map.md` documents ~45 of the codes the runtime can emit, so an
agent that hits an undocumented one pays a reference-doc read and still finds
nothing. This module answers the same question in the payload the agent already
parsed, for the families that actually recur in the fix loop.

Coverage is deliberately partial and cannot be otherwise:
`agent_protocol_submission.required_response_field` mints codes from
`f"MISSING_{field.upper()}"`, so the emitted set is open by construction. Every
unmatched code resolves through `_fallback`, never a KeyError.
"""

from __future__ import annotations

from gh_address_cr.core import command_templates, protocol_codes

_RESPONSE_SHAPE_CODES = frozenset(
    {
        "RESPONSE_FILE_NOT_FOUND",
        "INVALID_RESPONSE_JSON",
        "INVALID_RESPONSE_SHAPE",
        "BATCH_RESPONSE_FILE_NOT_FOUND",
        "INVALID_BATCH_RESPONSE_JSON",
        "INVALID_BATCH_RESPONSE_SHAPE",
    }
)

_PR_SCOPE_CODES = frozenset({"NO_ACTIVE_PR_SCOPE", "AMBIGUOUS_PR_SCOPE", "PARTIAL_PR_SCOPE"})


def _fallback(repo: str, pr_number: str) -> dict[str, str]:
    return {
        "summary": (
            "Read `reason_code` and `waiting_on`, then pick the matching template from `commands`. "
            "Consult `references/status-action-map.md` only if neither names the next step."
        ),
        "command": command_templates.address(repo, pr_number),
    }


def remediation_for(reason_code: str | None, *, repo: str, pr_number: str) -> dict[str, str]:
    """Map a reason_code to its next action, falling back for unregistered codes."""
    code = str(reason_code or "")

    if code in _RESPONSE_SHAPE_CODES:
        return {
            "summary": (
                "The response file is missing or is not the shape the runtime issued. "
                "Rewrite it from the `response_skeleton_path` in the ActionRequest, then resubmit."
            ),
            "command": command_templates.submit(repo, pr_number),
        }

    if code in _PR_SCOPE_CODES:
        return {
            "summary": (
                "The PR target could not be resolved from cached sessions. "
                "Pass `<owner/repo> <pr_number>` explicitly instead of relying on the implicit scope."
            ),
            "command": command_templates.address(repo, pr_number),
        }

    # MISSING_CLASSIFICATION_NOTE has no protocol_codes constant -- it's a raw literal
    # at its one call site (agent_protocol.py), not centralized there either.
    if code == protocol_codes.MISSING_CLASSIFICATION or code == "MISSING_CLASSIFICATION_NOTE":
        return {
            "summary": "Record triage classification evidence with a note before requesting a fixer lease.",
            "command": command_templates.classify(repo, pr_number),
        }

    if code == protocol_codes.MISSING_PUBLISH_REPLY or code == protocol_codes.MISSING_FIX_REPLY_COMMIT_HASH:
        return {
            "summary": (
                "Publish needs structured reply evidence: `fix_reply` must be a JSON object, "
                "and commit evidence must exist in the session or at Git HEAD."
            ),
            "command": command_templates.publish(repo, pr_number),
        }

    if code.startswith("MISSING_"):
        return {
            "summary": (
                f"The runtime rejected the submission for `{code}`. Add the named evidence field to the "
                "response file issued at `response_skeleton_path`, then resubmit — do not substitute a different field."
            ),
            "command": command_templates.submit(repo, pr_number),
        }

    return _fallback(repo, pr_number)
