"""Release-boundary contracts; no Homebrew installation or GitHub writes."""

from __future__ import annotations

import copy
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from scripts.release import homebrew_release as release
from scripts.release import homebrew_support as support
from scripts.release import verify_homebrew_install as installed
from scripts.release.render_homebrew_formula import render_formula

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://files.pythonhosted.org/packages/source/g/gh-address-cr/gh_address_cr-1.2.3.tar.gz"
SOURCE_HASH = "a" * 64
COMMIT = "b" * 40
RESOURCES = ({"name": "requests", "url": "https://files.pythonhosted.org/requests-2.34.0.tar.gz", "sha256": "c" * 64},)


def source_formula(resources=RESOURCES):
    return render_formula(
        class_name="GhAddressCr", url=SOURCE_URL, sha256=SOURCE_HASH,
        python_dependency="python@3.14", resources=resources, version="1.2.3",
    )


def snapshot():
    return support.make_snapshot(source_formula(), version="1.2.3", commit=COMMIT)


class ResourceSnapshotTests(unittest.TestCase):
    def test_stable_version_is_inferred_and_preview_version_is_explicit(self):
        stable = source_formula()
        self.assertNotIn('  version "', stable)
        self.assertEqual(snapshot()["version"], "1.2.3")
        preview = render_formula(class_name="GhAddressCrDev", url="https://github.com/example/source.tar.gz",
                                 sha256=SOURCE_HASH, python_dependency="python@3.14", resources=RESOURCES,
                                 conflicts_with=("gh-address-cr",), version="1.2.3.dev7+abcdef0")
        self.assertLess(preview.index('  version "'), preview.index('  sha256 "'))
        self.assertEqual(support.make_snapshot(preview, version="1.2.3.dev7+abcdef0", commit=COMMIT)["version"],
                         "1.2.3.dev7+abcdef0")
        with self.assertRaises(ValueError):
            support.make_snapshot(stable, version="1.2.4", commit=COMMIT)

    def test_installed_data_probe_uses_current_packaged_data(self):
        installed.verify_data_and_platform()

    def test_prepared_formula_is_a_checked_replay_input(self):
        manifest = snapshot()
        support.validate_snapshot(manifest, source_formula(), version="1.2.3", commit=COMMIT,
                                  source_url=SOURCE_URL, source_sha256=SOURCE_HASH)
        self.assertEqual(manifest["resources"], list(RESOURCES))

    def test_missing_malformed_or_unsafe_resources_fail(self):
        cases = [
            source_formula(()),
            source_formula().replace("c" * 64, "broken"),
            source_formula().replace("https://files.pythonhosted.org/requests", "https://user:secret@evil.test/requests"),
            source_formula() + "# RESOURCE-ERROR: unavailable\n",
            source_formula().replace("  resource ", "  resource ") + 'system "touch", "/tmp/untrusted"\n',
            source_formula() + source_formula()[source_formula().index('  resource "'):source_formula().index("  def install")],
        ]
        for formula in cases:
            with self.subTest(formula=formula[-100:]), self.assertRaises(ValueError):
                support.make_snapshot(formula, version="1.2.3", commit=COMMIT)

    def test_snapshot_tampering_and_source_drift_fail(self):
        original = snapshot()
        for key, value in (("version", "2.0.0"), ("commit", "d" * 40), ("source_sha256", "e" * 64)):
            changed = {**original, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                support.validate_snapshot(changed, source_formula(), version="1.2.3", commit=COMMIT,
                                          source_url=SOURCE_URL, source_sha256=SOURCE_HASH)
        with self.assertRaises(ValueError):
            support.validate_snapshot(original, source_formula() + "\n", version="1.2.3", commit=COMMIT,
                                      source_url=SOURCE_URL, source_sha256=SOURCE_HASH)

    def test_rendered_scaffold_is_not_publishable(self):
        with self.assertRaisesRegex(ValueError, "resource"):
            support.make_snapshot(source_formula(()), version="1.2.3", commit=COMMIT)


class ReleasePolicyTests(unittest.TestCase):
    def test_merged_homebrew_spec_must_preserve_every_bottle_checksum(self):
        expected = {tag: {"sha256": "a" * 64, "url": release.bottle_root("1.2.3") + f"/{tag}.tar.gz"}
                    for tag in support.TARGETS.values()}
        valid = {"rebuild": 0, "root_url": release.bottle_root("1.2.3"), "files": expected}
        release.validate_merged_bottles(valid, expected, version="1.2.3", rebuild=0)
        for bad in ({**valid, "files": dict(list(expected.items())[:-1])},
                    {**valid, "rebuild": 1},
                    {**valid, "files": {tag: {**row, "sha256": "b" * 64} for tag, row in expected.items()}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                release.validate_merged_bottles(bad, expected, version="1.2.3", rebuild=0)

    def test_tap_publication_requires_four_results_and_only_checks_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            formula = root / "gh-address-cr.rb"
            formula.write_text(source_formula())
            support.write_json(root / "publication.json", {"formula_sha256": support.digest(formula)})
            evidence = root / "evidence"
            evidence.mkdir()
            with mock.patch.object(release, "load_snapshot", return_value=(snapshot(), formula)), \
                 mock.patch.object(release, "publish_bottles") as assets, \
                 mock.patch.object(support, "update_tap") as tap:
                with self.assertRaisesRegex(ValueError, "four"):
                    release.publish_tap(root, evidence, root / "tap")
                assets.assert_not_called()
                tap.assert_not_called()
                for target in support.TARGETS:
                    support.write_json(evidence / f"verify-{target}.json", {
                        "target": target, "status": "passed", "formula_sha256": support.digest(formula)})
                release.publish_tap(root, evidence, root / "tap")
                assets.assert_called_once_with(root, verify_only=True)
                tap.assert_called_once()

    def test_all_four_unique_targets_must_pass(self):
        rows = [{"target": target, "status": "passed", "formula_sha256": "a" * 64}
                for target in support.TARGETS]
        support.require_all_targets(rows, "a" * 64)
        for bad in (rows[:-1], rows + [rows[0]], [{**rows[0], "status": "failed"}, *rows[1:]],
                    [{**rows[0], "formula_sha256": "b" * 64}, *rows[1:]]):
            with self.subTest(rows=bad), self.assertRaises(ValueError):
                support.require_all_targets(bad, "a" * 64)

    def test_preview_provenance_binds_repository_workflow_run_and_current_head(self):
        run = {"id": 123, "run_attempt": 1, "event": "pull_request", "conclusion": "success", "path": ".github/workflows/ci.yml",
               "head_sha": COMMIT, "head_repository": {"full_name": support.REPOSITORY},
               "pull_requests": [{"number": 7}]}
        pr = {"number": 7, "state": "open", "head": {"sha": COMMIT, "repo": {"full_name": support.REPOSITORY}}}
        metadata = {"run_id": 123, "run_attempt": 1, "pr": 7, "head_sha": COMMIT,
                    "version": f"1.2.3.dev7+{COMMIT[:7]}"}
        support.validate_preview(run, pr, metadata, run_id=123)
        cases = []
        for key, value in (("event", "push"), ("conclusion", "failure"), ("head_sha", "d" * 40),
                           ("path", ".github/workflows/untrusted.yml")):
            cases.append(({**run, key: value}, pr, metadata))
        foreign = copy.deepcopy(run)
        foreign["head_repository"]["full_name"] = "other/repo"
        cases.extend([(foreign, pr, metadata), (run, {**pr, "state": "closed"}, metadata),
                      (run, pr, {**metadata, "run_id": 456}),
                      (run, pr, {**metadata, "run_attempt": 2}),
                      (run, pr, {**metadata, "version": "1.2.3; unsafe"})])
        for candidate, pull, meta in cases:
            with self.subTest(run=candidate), self.assertRaises(ValueError):
                support.validate_preview(candidate, pull, meta, run_id=123)

    def test_preview_asset_name_is_immutable_and_contains_full_identity(self):
        name = support.preview_asset_name(7, COMMIT, 123, 2)
        self.assertIn(COMMIT, name)
        self.assertIn("123-2", name)
        self.assertNotEqual(name, support.preview_asset_name(7, COMMIT, 124, 1))


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "asset.json"
        self.file.write_text('{"valid": true}\n')

    def test_identical_asset_is_reused_and_different_bytes_fail(self):
        assets = support.ReleaseAssets("v1.2.3")
        with mock.patch.object(assets, "names", return_value={self.file.name}), \
             mock.patch.object(assets, "download", return_value=self.file), \
             mock.patch.object(support, "command") as command:
            assets.upload(self.file)
            command.assert_not_called()
            other = Path(self.temp.name) / "other"
            other.mkdir()
            changed = other / self.file.name
            changed.write_text("different")
            with self.assertRaisesRegex(ValueError, "immutable"):
                assets.upload(changed)
            command.assert_not_called()

    def test_missing_asset_is_uploaded_without_clobber(self):
        assets = support.ReleaseAssets("v1.2.3")
        with mock.patch.object(assets, "names", return_value=set()), \
             mock.patch.object(assets, "download", return_value=self.file) as download, \
             mock.patch.object(support, "command") as command:
            assets.upload(self.file)
        download.assert_called_once()
        argv = command.call_args.args[0]
        self.assertIn("upload", argv)
        self.assertNotIn("--clobber", argv)

    def test_upload_readback_mismatch_fails(self):
        other = Path(self.temp.name) / "corrupt"
        other.write_text("corrupt")
        assets = support.ReleaseAssets("v1.2.3")
        with mock.patch.object(assets, "names", return_value=set()), \
             mock.patch.object(assets, "download", return_value=other), \
             mock.patch.object(support, "command"), self.assertRaisesRegex(ValueError, "immutable"):
            assets.upload(self.file)


class BottleMergeTests(unittest.TestCase):
    def exercise_merge(self, *, change_source=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "gh-address-cr-1.2.3.homebrew-source.rb"
            source.write_text(source_formula())
            support.write_json(source.with_suffix(".json"), snapshot())
            builds = root / "builds"
            builds.mkdir()
            expected = {}
            for target, tag in support.TARGETS.items():
                filename = f"gh-address-cr-1.2.3.{tag}.bottle.tar.gz"
                bottle = builds / filename
                bottle.write_bytes(target.encode())
                checksum = support.digest(bottle)
                expected[tag] = {"sha256": checksum, "url": f"{release.bottle_root('1.2.3')}/{filename}"}
                support.write_json(builds / release.build_record_name("1.2.3", target, 0), {
                    "target": target, "formula_sha256": snapshot()["formula_sha256"],
                    "metadata": {support.FORMULA: {
                        "formula": {"pkg_version": "1.2.3"},
                        "bottle": {"root_url": release.bottle_root("1.2.3"), "rebuild": 0,
                                   "tags": {tag: {"filename": filename, "local_filename": filename,
                                                  "sha256": checksum}}},
                    }},
                })
            formula = root / "Formula" / "gh-address-cr.rb"
            formula.parent.mkdir()
            formula.write_text(source_formula())
            block = '  bottle do\n    root_url "' + release.bottle_root("1.2.3") + '"\n'
            block += "\n".join(f'    sha256 {tag}: "{row["sha256"]}"' for tag, row in expected.items())
            block += "\n  end"

            def brew(argv, **kwargs):
                if argv == ["brew", "--repository"]:
                    output = str(root)
                elif argv[:3] == ["brew", "bottle", "--merge"]:
                    # Homebrew FormulaAST inserts bottle before dependencies.
                    text = formula.read_text().replace('\n  depends_on', f'\n{block}\n\n  depends_on', 1)
                    if change_source:
                        text = text.replace('license "MIT"', 'license "Apache-2.0"')
                    formula.write_text(text)
                    output = ""
                elif argv[:2] == ["brew", "info"]:
                    output = json.dumps({"formulae": [{"bottle": {"stable": {
                        "root_url": release.bottle_root("1.2.3"), "rebuild": 0, "files": expected,
                    }}}]})
                else:
                    raise AssertionError(argv)
                return subprocess.CompletedProcess(argv, 0, output, "")

            with mock.patch.object(release, "stage_formula", return_value=formula), \
                 mock.patch.object(support, "command", side_effect=brew):
                release.merge(root / "publication", root, builds, 0)
            publication = json.loads((root / "publication/publication.json").read_text())
            self.assertEqual(publication["source_formula_sha256"], snapshot()["formula_sha256"])
            self.assertEqual(set(publication["targets"]), set(support.TARGETS))
            final = (root / "publication/gh-address-cr.rb").read_text()
            self.assertLess(final.index("  bottle do"), final.index("  depends_on"))

    def test_standard_homebrew_merge_preserves_snapshot_and_publishes_formula(self):
        self.exercise_merge()

    def test_merge_still_rejects_changes_outside_the_bottle_block(self):
        with self.assertRaisesRegex(ValueError, "changed source formula"):
            self.exercise_merge(change_source=True)


class FormulaStagingTests(unittest.TestCase):
    def test_staged_formula_is_trusted_individually_after_writing(self):
        for name in ("gh-address-cr", "gh-address-cr-dev"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                trusted = []

                def brew(argv, *, formula_name=name, tap_root=root, trusted_entries=trusted, **kwargs):
                    if argv[:2] == ["brew", "trust"]:
                        self.assertEqual(argv, ["brew", "trust", "--formula", f"{support.TAP}/{formula_name}"])
                        self.assertEqual((tap_root / "Formula" / f"{formula_name}.rb").read_text(), source_formula())
                        trusted_entries.append(argv[-1])
                    return subprocess.CompletedProcess(argv, 0, str(tap_root), "")

                with mock.patch.object(support, "command", side_effect=brew):
                    path = release.stage_formula(source_formula(), name)
                self.assertEqual(path.read_text(), source_formula())
                self.assertEqual(trusted, [f"{support.TAP}/{name}"])


class RecoveryTests(unittest.TestCase):
    def test_first_build_and_rebuild_use_supported_bottle_arguments(self):
        for rebuild in (0, 1):
            with self.subTest(rebuild=rebuild), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                target = "macos-15"

                def brew(argv, *, directory=directory, target=target, rebuild=rebuild, **kwargs):
                    if argv[:2] == ["brew", "bottle"]:
                        self.assertNotIn("--no-all-checks", argv,
                                         "Homebrew requires --merge with --no-all-checks")
                        self.assertIn("--keep-old" if rebuild else "--no-rebuild", argv)
                        bottle = directory / "local.bottle.tar.gz"
                        bottle.write_bytes(b"built bottle")
                        support.write_json(directory / "test.bottle.json", {support.FORMULA: {
                            "formula": {"pkg_version": "1.2.3"},
                            "bottle": {"root_url": release.bottle_root("1.2.3"), "rebuild": rebuild,
                                       "tags": {support.TARGETS[target]: {
                                           "local_filename": bottle.name, "filename": "remote.bottle.tar.gz",
                                           "sha256": support.digest(bottle)}}},
                        }})
                    return subprocess.CompletedProcess(argv, 0, "", "")

                with mock.patch.object(release, "load_snapshot", return_value=(snapshot(), directory)), \
                     mock.patch.object(release, "stage_formula"), \
                     mock.patch.object(support.ReleaseAssets, "names", return_value=set()), \
                     mock.patch.object(support, "command", side_effect=brew):
                    release.build(directory, directory, target, rebuild)
                record = json.loads((directory / release.build_record_name("1.2.3", target, rebuild)).read_text())
                self.assertEqual(record["target"], target)
                self.assertEqual((directory / "remote.bottle.tar.gz").read_bytes(), b"built bottle")

    def test_atomic_bundle_restores_after_partial_individual_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sealed, restored = root / "sealed", root / "restored"
            sealed.mkdir()
            restored.mkdir()
            target = next(iter(support.TARGETS))
            filename = "gh-address-cr-1.2.3.arm64_sequoia.bottle.tar.gz"
            bottle = sealed / filename
            bottle.write_bytes(b"immutable bottle")
            record = sealed / release.build_record_name("1.2.3", target, 0)
            support.write_json(record, {
                "target": target, "formula_sha256": snapshot()["formula_sha256"],
                "metadata": {support.FORMULA: {
                    "formula": {"pkg_version": "1.2.3"},
                    "bottle": {"root_url": release.bottle_root("1.2.3"), "rebuild": 0,
                               "tags": {support.TARGETS[target]: {
                                   "filename": filename, "local_filename": filename,
                                   "sha256": support.digest(bottle)}}},
                }},
            })
            bundle = release.recovery_bundle(sealed, record, [filename])
            first_hash = support.digest(bundle)
            self.assertEqual(support.digest(release.recovery_bundle(sealed, record, [filename])), first_hash)
            release.restore_bundle(bundle, restored, snapshot(), target, 0)
            self.assertEqual((restored / filename).read_bytes(), b"immutable bottle")
            self.assertEqual((restored / record.name).read_bytes(), record.read_bytes())

    def test_retry_restores_snapshot_without_resolving_again(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            formula_name, metadata_name = release.source_names("1.2.3")
            formula = directory / formula_name
            formula.write_text(source_formula())
            metadata = directory / metadata_name
            support.write_json(metadata, snapshot())
            with mock.patch.object(release, "stable_source", return_value=(COMMIT, SOURCE_URL, SOURCE_HASH)), \
                 mock.patch.object(support.ReleaseAssets, "names", return_value={formula_name, metadata_name}), \
                 mock.patch.object(support.ReleaseAssets, "download", side_effect=lambda name, _: directory / name), \
                 mock.patch.object(release, "resolve_formula") as resolver:
                release.prepare(directory, "1.2.3")
            resolver.assert_not_called()
            self.assertEqual(json.loads(metadata.read_text()), snapshot())

    def test_official_resolver_failure_does_not_produce_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "formula.rb"
            path.write_text(source_formula(()))
            with mock.patch.object(release, "stage_formula", return_value=path), \
                 mock.patch.object(support, "command", side_effect=ValueError("resolution conflict")), \
                 self.assertRaisesRegex(ValueError, "resolution conflict"):
                release.resolve_formula(version="1.2.3", commit=COMMIT, url=SOURCE_URL,
                                        sha=SOURCE_HASH, name="gh-address-cr")


class TapUpdateTests(unittest.TestCase):
    def test_inferred_stable_version_cannot_be_downgraded(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            target = work / "Formula/gh-address-cr.rb"
            target.parent.mkdir()
            target.write_text(source_formula().replace("1.2.3", "1.2.4"))
            with self.assertRaisesRegex(ValueError, "newer tap version"):
                support._write_and_push(work, "Formula/gh-address-cr.rb", source_formula().encode(),
                                        "gh-address-cr", "1.2.3")

    def test_real_git_preserves_concurrent_other_formula_and_is_idempotent(self):
        def git(*args):
            return subprocess.run(["git", *map(str, args)], check=True, capture_output=True, text=True)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            origin, checkout, writer = root / "origin.git", root / "checkout", root / "writer"
            git("init", "--bare", "--initial-branch=main", origin)
            git("clone", origin, checkout)
            git("-C", checkout, "config", "user.name", "test")
            git("-C", checkout, "config", "user.email", "test@example.invalid")
            (checkout / "Formula").mkdir()
            (checkout / "Formula/other.rb").write_text("first\n")
            git("-C", checkout, "add", ".")
            git("-C", checkout, "commit", "-m", "initial")
            git("-C", checkout, "push", "origin", "main")
            git("clone", origin, writer)
            git("-C", writer, "config", "user.name", "test")
            git("-C", writer, "config", "user.email", "test@example.invalid")
            formula = root / "candidate.rb"
            formula.write_text(source_formula())
            real_command = support.command
            raced = False

            def race(argv, **kwargs):
                nonlocal raced
                if argv[-3:] == ["push", "origin", "HEAD:main"] and not raced:
                    raced = True
                    (writer / "Formula/other.rb").write_text("concurrent\n")
                    git("-C", writer, "commit", "-am", "concurrent change")
                    git("-C", writer, "push", "origin", "main")
                return real_command(argv, **kwargs)

            with mock.patch.object(support, "command", side_effect=race):
                self.assertTrue(support.update_tap(checkout, formula, name="gh-address-cr", version="1.2.3"))
            self.assertTrue(raced)
            self.assertEqual(git("--git-dir", origin, "show", "main:Formula/other.rb").stdout, "concurrent\n")
            self.assertEqual(git("--git-dir", origin, "show", "main:Formula/gh-address-cr.rb").stdout,
                             source_formula())
            before = git("--git-dir", origin, "rev-parse", "main").stdout
            self.assertFalse(support.update_tap(checkout, formula, name="gh-address-cr", version="1.2.3"))
            self.assertEqual(git("--git-dir", origin, "rev-parse", "main").stdout, before)

    def test_dev_can_roll_to_a_lower_lexical_local_version(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            target = work / "Formula/gh-address-cr-dev.rb"
            target.parent.mkdir()
            target.write_text('  version "1.2.3.dev7+fffffff"\n')
            with mock.patch.object(support, "command", return_value=subprocess.CompletedProcess([], 0)):
                self.assertTrue(support._write_and_push(
                    work, "Formula/gh-address-cr-dev.rb", b'  version "1.2.3.dev7+aaaaaaa"\n',
                    "gh-address-cr-dev", "1.2.3.dev7+aaaaaaa"))

    def test_stable_rebuild_cannot_go_backwards(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            target = work / "Formula/gh-address-cr.rb"
            target.parent.mkdir()
            target.write_text('  version "1.2.3"\n  bottle do\n    rebuild 2\n  end\n')
            with self.assertRaisesRegex(ValueError, "rebuild"):
                support._write_and_push(work, "Formula/gh-address-cr.rb",
                                        b'  version "1.2.3"\n', "gh-address-cr", "1.2.3")


class ReleaseTelemetryTests(unittest.TestCase):
    def test_root_span_records_success_failure_and_sanitized_export_diagnostic(self):
        provider = TracerProvider()
        exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        stderr = io.StringIO()
        with mock.patch.object(support, "initialize_telemetry", return_value=provider.get_tracer("test")), \
             mock.patch.object(support, "shutdown_telemetry"), \
             mock.patch("sys.stderr", stderr):
            self.assertEqual(support.traced_main(lambda: 0), 0)
            self.assertEqual(support.traced_main(lambda: 7), 7)

            def diagnostic():
                logging.getLogger("opentelemetry.exporter.otlp.proto.http.trace_exporter").error(
                    "raw path /private/local and github_pat_secret")
                return 0

            self.assertEqual(support.traced_main(diagnostic), 0)
        roots = exporter.get_finished_spans()
        self.assertEqual([span.attributes["process.exit.code"] for span in roots], [0, 7, 0])
        self.assertTrue(all(span.kind == trace.SpanKind.INTERNAL for span in roots))
        self.assertTrue(all(span.attributes["process.pid"] > 0 for span in roots))
        self.assertIn("error.type", roots[1].attributes)
        self.assertIn("diagnostic", stderr.getvalue())
        self.assertNotIn("/private/local", stderr.getvalue())
        self.assertNotIn("github_pat_secret", stderr.getvalue())
        provider.shutdown()

    def test_timed_out_child_is_killed_and_reaped(self):
        process = mock.MagicMock()
        process.pid = 123
        process.communicate.side_effect = [subprocess.TimeoutExpired("tool", 3600), ("", "")]
        with mock.patch.object(support.subprocess, "Popen") as popen:
            popen.return_value.__enter__.return_value = process
            with self.assertRaises(subprocess.TimeoutExpired):
                support.command(["tool"])
        process.kill.assert_called_once()
        self.assertEqual(process.communicate.call_count, 2)

    def test_child_source_execution_does_not_inherit_publication_credentials(self):
        with mock.patch.dict(os.environ, {"GH_TOKEN": "secret", "GITHUB_TOKEN": "secret"}):
            result = support.command([sys.executable, "-c",
                                      "import os; print('GH_TOKEN' in os.environ or 'GITHUB_TOKEN' in os.environ)"])
        self.assertEqual(result.stdout.strip(), "False")

    def test_subprocess_span_has_identity_and_no_paths_or_secret_argv(self):
        provider = TracerProvider()
        exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        from gh_address_cr import otel_tracing

        with mock.patch.object(otel_tracing, "_active_tracer") as active:
            active.get.return_value = provider.get_tracer("release-test")
            with provider.get_tracer("release-test").start_as_current_span("root"):
                result = support.command([sys.executable, "-c", "raise SystemExit(7)", "github_pat_secret"],
                                         check=False)
        self.assertEqual(result.returncode, 7)
        spans = exporter.get_finished_spans()
        child = next(span for span in spans if span.kind == trace.SpanKind.CLIENT)
        self.assertGreater(child.attributes["process.pid"], 0)
        self.assertEqual(child.attributes["process.exit.code"], 7)
        self.assertIn("error.type", child.attributes)
        text = json.dumps(dict(child.attributes))
        self.assertNotIn("github_pat_secret", text)
        self.assertNotIn(sys.executable, text)
        provider.shutdown()

    def test_exporter_initialization_failure_does_not_skip_work(self):
        with mock.patch.object(support, "initialize_telemetry", side_effect=RuntimeError("private")), \
             mock.patch.object(support, "shutdown_telemetry"), \
             mock.patch.dict(os.environ, {"DISABLE_TELEMETRY": "1"}), \
             mock.patch("sys.stderr") as stderr:
            self.assertEqual(support.traced_main(lambda: 0), 0)
        self.assertTrue(stderr.write.called)


class WorkflowTrustTests(unittest.TestCase):
    def test_preview_rename_stages_consumer_before_changing_producer(self):
        root = ROOT / ".github/workflows"
        self.assertEqual((root / "ci.yml").read_text().splitlines()[0], "name: ci")
        preview = (root / "homebrew-preview.yml").read_text()
        names = preview.split("    workflows: [", 1)[1].split("]", 1)[0]
        self.assertEqual([value.strip().strip('"\'') for value in names.split(",")],
                         ["ci", "Checks / Python"])

    def test_workflow_run_routes_follow_producer_display_names(self):
        for producer, consumer in (("ci.yml", "homebrew-preview.yml"),
                                   ("release.yml", "sync-main-to-develop.yml")):
            with self.subTest(consumer=consumer):
                root = ROOT / ".github/workflows"
                name = (root / producer).read_text().splitlines()[0].removeprefix("name: ").strip('"\'')
                text = (root / consumer).read_text()
                triggers = text.split("    workflows: [", 1)[1].split("]", 1)[0]
                names = [value.strip().strip('"\'') for value in triggers.split(",")]
                self.assertIn(name, names)

    def test_pr_build_cannot_write_releases_or_mint_tap_credentials(self):
        ci = (ROOT / ".github/workflows/ci.yml").read_text()
        preview = ci.split("  pr-dev-preview:", 1)[1]
        self.assertNotIn("contents: write", preview)
        self.assertNotIn("RELEASE_BOT_PRIVATE_KEY", preview)
        self.assertNotIn("gh release upload", preview)
        self.assertNotIn("--clobber", preview)
        self.assertIn("preview.json", preview)

    def test_preview_publisher_uses_default_branch_and_triggering_run_artifact(self):
        workflow = (ROOT / ".github/workflows/homebrew-preview.yml").read_text()
        self.assertIn("workflow_run:", workflow)
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", workflow)
        self.assertIn("run-id: ${{ github.event.workflow_run.id }}", workflow)
        self.assertIn("needs: [inspect, publish-source]", workflow)
        self.assertIn("needs: [inspect, prepare]", workflow)
        self.assertIn("homebrew_preview publish", workflow)
        self.assertNotIn("pull_request_target:", workflow)


if __name__ == "__main__":
    unittest.main()
