import json
import tempfile
import unittest
from pathlib import Path

from app.telemetry_shutdown import read_last_shutdown_wait_ms, record_shutdown_wait, shutdown_wait_file


class ShutdownWaitTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.state_dir = Path(temp.name)

    def write(self, payload):
        shutdown_wait_file(self.state_dir).write_text(json.dumps(payload), encoding="utf-8")

    def test_round_trip(self):
        record_shutdown_wait(self.state_dir, 12.3456, timed_out=False)
        self.assertEqual(read_last_shutdown_wait_ms(self.state_dir), 12.346)

    def test_missing_record_is_none(self):
        self.assertIsNone(read_last_shutdown_wait_ms(self.state_dir))

    def test_rejects_negative_boolean_and_text(self):
        for value in (-1, True, "12"):
            with self.subTest(value=value):
                self.write({"wait_ms": value})
                self.assertIsNone(read_last_shutdown_wait_ms(self.state_dir))

    def test_rejects_non_finite_values(self):
        for literal in ("NaN", "Infinity"):
            with self.subTest(literal=literal):
                shutdown_wait_file(self.state_dir).write_text('{"wait_ms": %s}' % literal, encoding="utf-8")
                self.assertIsNone(read_last_shutdown_wait_ms(self.state_dir))


if __name__ == "__main__":
    unittest.main()
