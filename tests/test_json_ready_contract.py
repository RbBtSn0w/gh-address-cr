from __future__ import annotations

import json
import unittest
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from gh_address_cr.core.io import json_ready as io_json_ready
from gh_address_cr.core.utils import json_ready as utils_json_ready


@dataclass
class _Inner:
    label: str


@dataclass
class _Outer:
    name: str
    inner: _Inner
    tags: list[str] = field(default_factory=list)


class _Plain:
    def __init__(self, value: str) -> None:
        self.value = value


class JsonReadyContractTestCase(unittest.TestCase):
    """`core.io` and `core.utils` must expose one normalizer, not two.

    They used to be separate hand-rolled copies that diverged: `io` handled
    dataclasses and `Path` but not arbitrary `__dict__` objects, while `utils`
    handled `__dict__` but neither dataclasses nor `Path`. The same value could
    therefore serialize differently depending on which module a caller imported
    from — and `core.ids` hashes the `utils` output into deterministic IDs.
    """

    def _both(self, value: object) -> object:
        via_io = io_json_ready(value)
        via_utils = utils_json_ready(value)
        self.assertEqual(via_io, via_utils, "core.io and core.utils must agree")
        return via_io

    def test_dataclass_expands_recursively_through_both_entry_points(self) -> None:
        result = self._both(_Outer(name="outer", inner=_Inner(label="in"), tags=["a", "b"]))
        self.assertEqual(result, {"name": "outer", "inner": {"label": "in"}, "tags": ["a", "b"]})

    def test_path_becomes_a_string_through_both_entry_points(self) -> None:
        self.assertEqual(self._both(Path("/tmp/example/file.json")), "/tmp/example/file.json")

    def test_plain_object_expands_via_dict_through_both_entry_points(self) -> None:
        self.assertEqual(self._both(_Plain("v")), {"value": "v"})

    def test_datetime_becomes_isoformat_through_both_entry_points(self) -> None:
        moment = datetime(2026, 8, 25, 12, 30, tzinfo=timezone.utc)
        self.assertEqual(self._both(moment), moment.isoformat())

    def test_nested_mixture_is_json_serializable(self) -> None:
        payload = {
            "path": Path("/var/data"),
            "record": _Outer(name="n", inner=_Inner(label="l")),
            "object": _Plain("x"),
            "when": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "items": ({"k": 1}, [Path("/a")]),
        }
        result = self._both(payload)
        json.dumps(result, sort_keys=True)
        self.assertEqual(result["path"], "/var/data")
        self.assertEqual(result["object"], {"value": "x"})
        self.assertEqual(result["items"], [{"k": 1}, ["/a"]])

    def test_scalars_and_containers_are_unchanged(self) -> None:
        self.assertIsNone(self._both(None))
        self.assertEqual(self._both("s"), "s")
        self.assertEqual(self._both(3), 3)
        self.assertEqual(self._both(True), True)
        self.assertEqual(self._both({"a": [1, 2]}), {"a": [1, 2]})
        self.assertEqual(self._both({1: "x"}), {"1": "x"})

    def test_str_enum_stays_a_string_through_both_entry_points(self) -> None:
        """`AgentRole` is a `str` Enum and must survive as its string value.

        Expanding it through the `__dict__` branch would emit enum internals,
        and the `__objclass__` back-reference would drag in an unserializable
        `mappingproxy`. `core.utils` used to do exactly that, which meant a role
        passed as an enum instead of a string produced a different
        `core.ids` fingerprint for the same logical payload.
        """
        from gh_address_cr.agent.roles import AgentRole

        for value in (AgentRole.FIXER, {"role": AgentRole.FIXER}):
            with self.subTest(value=value):
                result = self._both(value)
                json.dumps(result, sort_keys=True)

        self.assertEqual(json.dumps(self._both(AgentRole.FIXER)), json.dumps("fixer"))
        self.assertEqual(
            utils_json_ready({"role": AgentRole.FIXER}),
            utils_json_ready({"role": "fixer"}),
        )

    def test_class_objects_are_not_expanded(self) -> None:
        self.assertIs(self._both(_Plain), _Plain)

    def test_flat_dataclass_hashes_the_same_as_the_previous_vars_expansion(self) -> None:
        """Guards the deterministic IDs in `core.ids` across this consolidation.

        `utils.json_ready` previously expanded objects with `vars()`. For a flat
        dataclass `asdict()` produces the identical mapping, so no existing
        fingerprint changes value.
        """
        record = _Inner(label="in")
        self.assertEqual(utils_json_ready(record), vars(record))


if __name__ == "__main__":
    unittest.main()
