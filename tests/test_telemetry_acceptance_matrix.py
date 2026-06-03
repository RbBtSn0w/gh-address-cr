import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "specs" / "015-external-agent-telemetry" / "acceptance-matrix.md"

REQUIRED_CATEGORIES = {
    "safe-accept",
    "unsafe-reject",
    "fail-open",
    "fail-loud",
    "idempotence",
    "coverage",
    "statistics",
    "archive",
    "host-hook",
}


class TestTelemetryAcceptanceMatrix(unittest.TestCase):
    """
    Test Intent
    Risk: Telemetry requirements are broad enough that future changes can satisfy
    isolated review comments while leaving adjacent safety, reporting, or
    statistics boundaries uncovered.
    Why Automation: Manual spec review already missed adjacent sanitizer,
    fail-open, and threshold cases; a machine check prevents the matrix from
    drifting into narrative-only documentation.
    Why Existing Tests Insufficient: Existing behavior tests prove individual
    cases, but no test proves that the documented telemetry risk matrix maps
    every acceptance row to executable regression evidence.
    Chosen Layer: Unit Test - parses the spec-owned matrix and checks referenced
    unittest methods exist without invoking live GitHub or filesystem state.
    Fragility Analysis: The test depends on stable test method names and a simple
    markdown table contract; that is intentional because renamed tests should
    update the acceptance matrix in the same change.
    If Omitted: The project can regress to CR-driven discovery where the spec
    says the right thing but no artifact proves each risk dimension is tested.
    """

    def test_acceptance_matrix_exists_and_maps_to_executable_tests(self):
        self.assertTrue(MATRIX_PATH.exists(), f"missing telemetry acceptance matrix: {MATRIX_PATH}")
        matrix = _parse_matrix(MATRIX_PATH.read_text(encoding="utf-8"))
        self.assertEqual(REQUIRED_CATEGORIES, {row["category"] for row in matrix})
        self.assertEqual(len(matrix), len({row["id"] for row in matrix}), "matrix ids must be unique")

        available_tests = _discover_test_methods()
        for row in matrix:
            evidence = row["evidence_tests"]
            self.assertTrue(evidence, f"{row['id']} must cite at least one executable test")
            missing = [test_name for test_name in evidence if test_name not in available_tests]
            self.assertEqual([], missing, f"{row['id']} cites missing tests")


def _parse_matrix(markdown: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("| TM-"):
            continue
        columns = [column.strip() for column in stripped.strip("|").split("|")]
        if len(columns) != 5:
            raise AssertionError(f"invalid matrix row: {line}")
        rows.append(
            {
                "id": columns[0],
                "category": columns[1],
                "requirement": columns[2],
                "safe_near_miss": columns[3],
                "evidence_tests": re.findall(r"`([^`]+)`", columns[4]),
            }
        )
    return rows


def _discover_test_methods() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "tests").rglob("test_*.py"):
        module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name.startswith("test_"):
                    names.add(f"{module}.{node.name}.{child.name}")
                    names.add(f"{module.removeprefix('tests.')}.{node.name}.{child.name}")
    return names
