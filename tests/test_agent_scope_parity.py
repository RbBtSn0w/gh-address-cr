"""#122: every agent subcommand resolves PR scope through one uniform path."""

import contextlib
import io
import json
import unittest
from unittest import mock

from gh_address_cr.commands import agent


class AgentScopeParityTest(unittest.TestCase):
    SCOPE_AWARE_HANDLERS = (
        "handle_agent_classify",
        "handle_agent_next",
        "handle_agent_submit",
        "handle_agent_resolve",
        "handle_agent_publish",
        "handle_agent_leases",
        "handle_agent_reclaim",
    )

    def test_unresolved_scope_is_reported_uniformly(self):
        # No cached sessions -> every scope-aware command must emit the same
        # NO_ACTIVE_PR_SCOPE resolution error before argparse, not a per-command
        # ad-hoc failure.
        with mock.patch("gh_address_cr.commands.common.active_cached_sessions", return_value=[]):
            for name in self.SCOPE_AWARE_HANDLERS:
                with self.subTest(handler=name):
                    handler = getattr(agent, name)
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        rc = handler(None, [])
                    payload = json.loads(buf.getvalue())
                    self.assertEqual(payload["reason_code"], "NO_ACTIVE_PR_SCOPE")
                    self.assertEqual(rc, payload["exit_code"])


if __name__ == "__main__":
    unittest.main()
