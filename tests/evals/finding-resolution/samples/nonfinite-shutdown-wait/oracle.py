"""Hidden oracle: non-finite persisted waits are rejected and valid ones still read."""

import tempfile
import unittest
from pathlib import Path

from app.telemetry_shutdown import read_last_shutdown_wait_ms, shutdown_wait_file


class Oracle(unittest.TestCase):
    def read_raw(self, text):
        with tempfile.TemporaryDirectory() as temp:
            shutdown_wait_file(Path(temp)).write_text(text, encoding="utf-8")
            return read_last_shutdown_wait_ms(Path(temp))

    def test_non_finite_values_are_rejected(self):
        for literal in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(literal=literal):
                self.assertIsNone(self.read_raw('{"wait_ms": %s}' % literal))

    def test_finite_values_still_read(self):
        self.assertEqual(self.read_raw('{"wait_ms": 42.5}'), 42.5)
        self.assertEqual(self.read_raw('{"wait_ms": 0}'), 0.0)

    def test_existing_rejections_are_preserved(self):
        for literal in ("-1", "true", '"12"'):
            with self.subTest(literal=literal):
                self.assertIsNone(self.read_raw('{"wait_ms": %s}' % literal))
