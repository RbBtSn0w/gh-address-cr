import unittest
from datetime import timezone

from gh_address_cr.core.utils import parse_iso_datetime


class ParseIsoDatetimeTests(unittest.TestCase):
    def test_naive_input_coerced_to_utc(self):
        parsed = parse_iso_datetime("2026-06-21T10:00:00")
        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.hour, 10)

    def test_z_suffix_is_utc(self):
        parsed = parse_iso_datetime("2026-06-21T10:00:00Z")
        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.hour, 10)

    def test_aware_offset_converted_to_utc(self):
        # Regression: aware inputs must be normalized to UTC, matching the
        # docstring, instead of returned with their original offset.
        parsed = parse_iso_datetime("2026-06-21T12:00:00+02:00")
        self.assertEqual(parsed.utcoffset(), timezone.utc.utcoffset(None))
        self.assertEqual(parsed.hour, 10)

    def test_invalid_or_nonstring_returns_none(self):
        self.assertIsNone(parse_iso_datetime("not-a-date"))
        self.assertIsNone(parse_iso_datetime(None))
        self.assertIsNone(parse_iso_datetime(123))


if __name__ == "__main__":
    unittest.main()
