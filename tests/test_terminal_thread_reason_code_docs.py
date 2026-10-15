"""The reason codes agents repeatedly stall on (#366) must each carry a documented remedy.

Every code below already had runtime handling, but an agent following the skill
docs hit them as dead ends: it blamed a short SHA for `COMMIT_NOT_IN_PR`, did not
know `--closed` or `--stale` existed, or called `agent next` before
`agent classify`. Each code needs its own `status-action-map.md` entry naming the
specific remedy, and a pointer from `SKILL.md`. Codes are imported from the
runtime so a rename breaks this test instead of silently orphaning the docs.
"""

import re
import unittest

from gh_address_cr.core import protocol_codes
from gh_address_cr.core.runtime_kernel.final_gate import FINAL_GATE_MISSING_REPLY_EVIDENCE
from tests.helpers import ROOT

STATUS_ACTION_MAP = ROOT / "skill" / "references" / "status-action-map.md"
AGENT_PROTOCOL = ROOT / "skill" / "references" / "agent-protocol.md"
SKILL_MD = ROOT / "skill" / "SKILL.md"

# reason code -> tokens its status-action-map entry must name.
REMEDIES = {
    protocol_codes.COMMIT_NOT_IN_PR: ("push", "four characters", "`HEAD`"),
    FINAL_GATE_MISSING_REPLY_EVIDENCE: ("--closed",),
    protocol_codes.STALE_THREADS_REQUIRE_RESOLVE_STALE: ("--input", "--stale", "--commit"),
    protocol_codes.MISSING_CLASSIFICATION: ("agent classify", "agent resolve"),
    # Raised by `agent classify` itself on an empty note, not by `agent next`.
    "MISSING_CLASSIFICATION_NOTE": ("--note",),
}


def _status_action_entry(text: str, code: str) -> str:
    """Return the action paragraph of the `If reason_code is ...` entry that names `code`."""
    pattern = re.compile(
        r"^If `reason_code` is [^\n]*`" + re.escape(code) + r"`[^\n]*:\n(- \*\*Action\*\*:[^\n]*)",
        re.MULTILINE,
    )
    match = pattern.search(text)
    return match.group(1) if match else ""


class TerminalThreadReasonCodeDocsTests(unittest.TestCase):
    def test_each_code_has_a_status_action_entry_with_its_remedy(self):
        text = STATUS_ACTION_MAP.read_text(encoding="utf-8")
        for code, tokens in REMEDIES.items():
            with self.subTest(reason_code=code):
                entry = _status_action_entry(text, code)
                self.assertTrue(entry, f"status-action-map.md has no `If reason_code is {code}` entry")
                for token in tokens:
                    self.assertIn(token, entry)

    def test_skill_md_points_at_each_code(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        for code in REMEDIES:
            with self.subTest(reason_code=code):
                self.assertIn(f"`{code}`", text)

    def test_docs_do_not_claim_a_full_sha_is_required(self):
        # `commit_membership.commit_in_pr` accepts any prefix of four or more characters.
        full_sha = r"(?i)\bfull\s+(?:40\b|(?:commit\s+)?sha\b)|\b40[\s-]+char"
        for path in (STATUS_ACTION_MAP, AGENT_PROTOCOL, SKILL_MD):
            with self.subTest(path=path.name):
                self.assertNotRegex(path.read_text(encoding="utf-8"), full_sha)
        for phrase in ("Pass the full SHA", "use the full commit SHA", "a 40 character hash", "full 40-char"):
            with self.subTest(phrase=phrase):
                self.assertRegex(phrase, full_sha)


if __name__ == "__main__":
    unittest.main()
