import unittest
from datetime import datetime, timezone

from gh_address_cr.core.ids import stable_id, stable_payload_hash


class StableIdTest(unittest.TestCase):
    def test_stable_payload_hash_is_order_independent_and_datetime_safe(self):
        left = {"b": 2, "a": datetime(2026, 6, 13, tzinfo=timezone.utc)}
        right = {"a": datetime(2026, 6, 13, tzinfo=timezone.utc), "b": 2}

        self.assertEqual(stable_payload_hash(left), stable_payload_hash(right))

    def test_stable_id_uses_prefix_and_twenty_hash_chars(self):
        value = stable_id("req", {"item_id": "github-thread:abc", "lease_id": "lease-1"})

        self.assertRegex(value, r"^req_[0-9a-f]{20}$")


if __name__ == "__main__":
    unittest.main()

