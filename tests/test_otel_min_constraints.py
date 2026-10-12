import importlib.metadata as metadata
import re
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path

from tests.helpers import ROOT

SCRIPT = ROOT / "scripts" / "otel_min_constraints.py"
OTEL_PACKAGES = ("opentelemetry-api", "opentelemetry-exporter-otlp-proto-http", "opentelemetry-sdk")


def run_script(*args: str, dependencies: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the script, against a throwaway pyproject.toml when `dependencies` is given."""
    with tempfile.TemporaryDirectory() as directory:
        command = [sys.executable, str(SCRIPT), *args]
        if dependencies is not None:
            pyproject = Path(directory) / "pyproject.toml"
            quoted = ", ".join(f'"{spec}"' for spec in dependencies)
            pyproject.write_text(
                textwrap.dedent(f'[project]\nname = "x"\ndependencies = [{quoted}]\n'),
                encoding="utf-8",
            )
            command += ["--pyproject", str(pyproject)]
        return subprocess.run(command, capture_output=True, text=True, check=False)


class OtelMinConstraintsTest(unittest.TestCase):
    def test_pins_every_declared_opentelemetry_floor_exactly(self):
        declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
        expected = {
            f"{name}=={version}"
            for name, version in (spec.split(">=", 1) for spec in declared if spec.startswith("opentelemetry-"))
        }

        result = run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(result.stdout.split()), expected)
        self.assertEqual(len(expected), len(OTEL_PACKAGES))
        self.assertNotIn(">=", result.stdout, "a '>=' constraint would pin nothing and test the newest release")

    def test_ignores_dependencies_that_are_not_opentelemetry(self):
        result = run_script(dependencies=["opentelemetry-sdk>=1.40", "requests>=2.31.0", "packaging>=24"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["opentelemetry-sdk==1.40"])

    def test_pins_use_canonical_package_names_whatever_the_spelling(self):
        # Package names are case-insensitive and treat '-', '_' and '.' alike. A spelling that skips the
        # opentelemetry- prefix check would leave the sdk unpinned without any error.
        result = run_script(
            dependencies=["OpenTelemetry-SDK>=1.40", "OpenTelemetry_API>=1.40", "opentelemetry.exporter.otlp.proto.http>=1.40"]
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.split(),
            [
                "opentelemetry-api==1.40",
                "opentelemetry-exporter-otlp-proto-http==1.40",
                "opentelemetry-sdk==1.40",
            ],
        )

    def test_refuses_an_opentelemetry_spec_it_cannot_pin(self):
        # Silently skipping these would leave the sdk, and with it semantic-conventions, unpinned
        # while the job still looked green.
        for spec in (
            "opentelemetry-sdk>=1.40,<2",
            "opentelemetry-sdk[extra]>=1.40",
            "opentelemetry-sdk~=1.40",
            "opentelemetry-sdk>=1.40; python_version >= '3.12'",
            "opentelemetry-sdk",
            "OpenTelemetry_SDK[extra]>=1.40",
        ):
            with self.subTest(spec=spec):
                result = run_script(dependencies=["opentelemetry-api>=1.40", spec])
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("opentelemetry-sdk", result.stderr.lower().replace("_", "-"))
                self.assertEqual(result.stdout, "", "no partial constraints may be emitted on failure")

    def test_refuses_a_pyproject_without_opentelemetry_dependencies(self):
        result = run_script(dependencies=["requests>=2.31.0"])

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("opentelemetry", result.stderr)

    def test_check_installed_accepts_the_versions_that_are_installed(self):
        installed = {name: metadata.version(name) for name in OTEL_PACKAGES}

        result = run_script("--check-installed", dependencies=[f"{n}>={v}" for n, v in installed.items()])

        self.assertEqual(result.returncode, 0, result.stderr)
        for name, version in installed.items():
            self.assertRegex(result.stdout, rf"{re.escape(name)}\s+{re.escape(version)}")
        self.assertIn("opentelemetry-semantic-conventions", result.stdout)

    def test_check_installed_rejects_a_version_above_the_floor(self):
        # The point of the CI job is to run at the floor; a newer install means the pin did not apply.
        result = run_script("--check-installed", dependencies=["opentelemetry-sdk>=1.0"])

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("opentelemetry-sdk", result.stderr)
        self.assertIn("1.0", result.stderr)

    def test_check_installed_rejects_a_missing_package(self):
        result = run_script("--check-installed", dependencies=["opentelemetry-not-a-real-package>=1.0"])

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("opentelemetry-not-a-real-package", result.stderr)
        self.assertIn("not installed", result.stderr)


if __name__ == "__main__":
    unittest.main()
