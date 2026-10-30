"""Hidden oracle: the unused parameter is gone and the reopen path still works."""

import inspect
import unittest

from app.commands import reply_to_closed_thread
from app.threads import reopen_resolved_thread_for_reply


class Oracle(unittest.TestCase):
    def test_agent_id_is_not_a_parameter(self):
        self.assertNotIn("agent_id", inspect.signature(reopen_resolved_thread_for_reply).parameters)

    def test_reopen_still_works(self):
        state = {"items": {"t1": {"status": "CLOSED", "remote_resolved": True}}}
        self.assertEqual(reply_to_closed_thread(state, "t1", "agent-1")["status"], "OPEN")
