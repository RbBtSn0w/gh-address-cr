import unittest

from tests.helpers import ROOT

STATUS_ACTION_MAP = ROOT / "skill" / "references" / "status-action-map.md"
COMPLETION_CONTRACT = ROOT / "skill" / "references" / "completion-contract.md"
SKILL_MD = ROOT / "skill" / "SKILL.md"
QUICKSTART = ROOT / "specs" / "028-workflow-gap-recovery" / "quickstart.md"
RECOVERY_CONTRACT = ROOT / "specs" / "028-workflow-gap-recovery" / "contracts" / "recovery-surface.md"
ENVIRONMENT_CONTRACT = ROOT / "specs" / "028-workflow-gap-recovery" / "contracts" / "environment-diagnostics.md"


class WorkflowGapRecoveryDocsSyncTests(unittest.TestCase):
    def test_reply_reconcile_guidance_is_aligned(self):
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (STATUS_ACTION_MAP, SKILL_MD, QUICKSTART, RECOVERY_CONTRACT)
        )

        self.assertIn("FINAL_GATE_MISSING_REPLY_EVIDENCE", combined)
        self.assertIn("agent evidence add", combined)
        self.assertIn("--reply-url", combined)
        self.assertIn("reconcile", combined)

    def test_lease_locked_guidance_is_aligned(self):
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (STATUS_ACTION_MAP, SKILL_MD, QUICKSTART, RECOVERY_CONTRACT)
        )

        self.assertIn("LEASE_LOCKED_ITEM", combined)
        self.assertIn("agent leases", combined)
        self.assertIn("lease_recovery", combined)

    def test_runtime_only_and_permission_mismatch_guidance_are_aligned(self):
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (STATUS_ACTION_MAP, COMPLETION_CONTRACT, SKILL_MD, ENVIRONMENT_CONTRACT)
        )

        self.assertIn("runtime-only", combined)
        self.assertIn("advisory", combined)
        self.assertIn("GH_PERMISSION_MISMATCH", combined)
        self.assertIn("github_permission", combined)
