import unittest

from gh_address_cr.core import protocol_codes


class TestProtocolCodes(unittest.TestCase):
    def _public_constants(self):
        return {
            name: getattr(protocol_codes, name)
            for name in dir(protocol_codes)
            if name.isupper() and not name.startswith("_")
        }

    def test_each_constant_value_equals_its_name(self):
        # Guards against definition typos like `FOO = "FOOO"` that would silently
        # change the wire/protocol value while reading correctly at call sites.
        for name, value in self._public_constants().items():
            self.assertEqual(name, value, f"{name} must equal its string value")

    def test_constant_values_are_unique(self):
        values = list(self._public_constants().values())
        self.assertEqual(len(values), len(set(values)), "duplicate protocol code values")

    def test_module_has_no_runtime_imports(self):
        # protocol_codes must stay dependency-free so any module can use it without cycles.
        source = __import__("inspect").getsource(protocol_codes)
        for line in source.splitlines():
            stripped = line.strip()
            self.assertFalse(
                stripped.startswith("import ") or (stripped.startswith("from ") and "__future__" not in stripped),
                f"protocol_codes must have no runtime imports, found: {stripped}",
            )


if __name__ == "__main__":
    unittest.main()
