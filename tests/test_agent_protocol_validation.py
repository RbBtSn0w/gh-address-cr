import unittest

from gh_address_cr.commands.agent import _parse_agent_validation
from gh_address_cr.core.agent_protocol_validation import (
    normalize_validation_command_records,
    split_validation_command_record,
)


class ValidationRecordTimingTests(unittest.TestCase):
    def test_split_validation_record_parses_ms_suffix(self):
        command, result, duration = split_validation_command_record("ruff check=passed@1500ms")
        self.assertEqual(command, "ruff check")
        self.assertEqual(result, "passed")
        self.assertEqual(duration, 1.5)

    def test_split_validation_record_parses_seconds_suffix(self):
        command, result, duration = split_validation_command_record("pytest=failed@3.5s")
        self.assertEqual(command, "pytest")
        self.assertEqual(result, "failed")
        self.assertEqual(duration, 3.5)

    def test_split_validation_record_without_suffix_has_no_duration(self):
        command, result, duration = split_validation_command_record("ruff check=passed")
        self.assertEqual(command, "ruff check")
        self.assertEqual(result, "passed")
        self.assertIsNone(duration)

    def test_split_validation_record_bare_command_unchanged(self):
        command, result, duration = split_validation_command_record("ruff check")
        self.assertEqual(command, "ruff check")
        self.assertEqual(result, "passed")
        self.assertIsNone(duration)

    def test_normalize_carries_duration_from_string_suffix(self):
        records = normalize_validation_command_records(["ruff check=passed@1500ms"])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["command"], "ruff check")
        self.assertEqual(records[0]["result"], "passed")
        self.assertEqual(records[0]["duration"], 1.5)

    def test_split_tolerates_whitespace_around_equals_without_truncation(self):
        # Regression: searching on stripped value but slicing the unstripped value
        # truncated the result token (e.g. "passed" -> "passe") when spaces were present.
        command, result, duration = split_validation_command_record("ruff check = passed@1500ms")
        self.assertEqual(command, "ruff check")
        self.assertEqual(result, "passed")
        self.assertEqual(duration, 1.5)


class CliValidationParseTimingTests(unittest.TestCase):
    """The `--validation` CLI flag must honor the same `@<n>ms`/`@<n>s` timing
    suffix the core normalizer accepts; otherwise the documented
    `agent resolve ... --validation cmd=passed@1500ms` records zero duration."""

    def test_parse_agent_validation_captures_ms_suffix(self):
        records = _parse_agent_validation(["unit-tests=passed@4200ms"])
        self.assertEqual(records, [{"command": "unit-tests", "result": "passed", "duration": 4.2}])

    def test_parse_agent_validation_captures_seconds_suffix(self):
        records = _parse_agent_validation(["pytest=failed@3.5s"])
        self.assertEqual(records, [{"command": "pytest", "result": "failed", "duration": 3.5}])

    def test_parse_agent_validation_without_suffix_has_no_duration(self):
        records = _parse_agent_validation(["ruff check=passed"])
        self.assertEqual(records, [{"command": "ruff check", "result": "passed"}])

    def test_parse_agent_validation_preserves_env_assignment_command(self):
        records = _parse_agent_validation(["PYENV_VERSION=3.10.19 python -m unittest"])
        self.assertEqual(
            records,
            [{"command": "PYENV_VERSION=3.10.19 python -m unittest", "result": "passed"}],
        )


if __name__ == "__main__":
    unittest.main()
