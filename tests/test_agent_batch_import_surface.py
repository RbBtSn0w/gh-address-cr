"""Guard against agent_batch.py regrowing a private cross-module import surface.

Before the agent_protocol.py module split (issue #227 item 2), agent_batch.py
imported 18 underscore-prefixed "private" names from agent_protocol.py because
the shared request/lease/response pipeline it needed was physically embedded
there. That pipeline now lives in agent_protocol_leases.py and
agent_protocol_submission.py as peer modules agent_batch.py imports from
directly, so it should never again need to reach into another module's
underscore-prefixed internals to get its work done.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

AGENT_BATCH_PATH = Path(__file__).resolve().parent.parent / "src" / "gh_address_cr" / "core" / "agent_batch.py"
_PROTOCOL_MODULE_PREFIX = "gh_address_cr.core.agent_protocol"


class AgentBatchImportSurfaceTests(unittest.TestCase):
    def test_no_private_names_imported_from_agent_protocol_modules(self) -> None:
        tree = ast.parse(AGENT_BATCH_PATH.read_text(encoding="utf-8"), filename=str(AGENT_BATCH_PATH))
        private_imports: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if not node.module.startswith(_PROTOCOL_MODULE_PREFIX):
                continue
            for alias in node.names:
                if alias.name.startswith("_"):
                    private_imports.append(f"{node.module}.{alias.name}")

        self.assertEqual(
            private_imports,
            [],
            "agent_batch.py must import only public names from agent_protocol* "
            f"modules; found private imports: {private_imports}",
        )


if __name__ == "__main__":
    unittest.main()
