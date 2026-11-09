"""Main-only release authority and immutable candidate handoff contracts."""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ScheduledReleaseContract(unittest.TestCase):
    def test_legacy_preview_producer_is_absent(self):
        ci = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertNotIn('pr-dev-preview:', ci)
        self.assertNotIn('name: gh-address-cr-dist', ci)

    def test_freshness_fails_closed(self):
        script = ROOT / 'scripts/release/check-main.sh'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / 'git'
            for response, code, accepted in [('a' * 40 + '\trefs/heads/main', 0, True), ('', 0, False), ('b' * 40 + '\trefs/heads/main', 0, False), ('', 1, False)]:
                fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "{response}"\nexit {code}\n')
                fake.chmod(0o755)
                import os
                result = subprocess.run(['bash', str(script), 'a' * 40], env={**os.environ, 'PATH': str(root) + ':' + os.environ['PATH']}, capture_output=True)
                self.assertEqual(result.returncode == 0, accepted)

    def test_handoff_rejects_tamper_extra_files_and_wrong_sha(self):
        import hashlib
        import json

        from scripts.release.handoff import inventory, verify
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = 'a' * 40
            (root / 'product.whl').write_bytes(b'wheel')
            (root / 'product.tar.gz').write_bytes(b'sdist')
            plugin = root / 'plugin/package/.codex-plugin/plugin.json'
            plugin.parent.mkdir(parents=True)
            plugin.write_text('{"name":"fixture"}')
            (root / 'plan.json').write_text(json.dumps({'completed': True, 'candidate': candidate, 'version': '1.2.3'}))
            (root / 'handoff.json').write_text(json.dumps({'candidate': candidate, 'files': inventory(root)}))
            self.assertEqual(verify(root, candidate)['version'], '1.2.3')
            content = plugin.read_bytes()
            plugin.unlink()
            with self.assertRaises(ValueError):
                verify(root, candidate)
            plugin.write_bytes(content)
            with self.assertRaises(ValueError):
                verify(root, 'b' * 40)
            (root / 'extra').write_bytes(b'unexpected')
            with self.assertRaises(ValueError):
                verify(root, candidate)
            (root / 'extra').unlink()
            (root / 'product.whl').write_bytes(hashlib.sha256(b'changed').digest())
            with self.assertRaises(ValueError):
                verify(root, candidate)

    def test_verified_artifact_upload_preserves_hidden_plugin_manifests(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
        producer, = [step for step in workflow['jobs']['verify']['steps']
                     if step.get('id') == 'artifact']
        self.assertEqual(producer['uses'], 'actions/upload-artifact@v4')
        self.assertEqual(producer['with']['path'], 'dist/')
        self.assertIs(producer['with'].get('include-hidden-files'), True)

    def test_event_matrix_permissions_and_publisher_never_builds(self):
        import itertools

        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
        expression = workflow['jobs']['verify']['if']
        for enabled, ref, event in itertools.product(('true', '', 'false'), ('refs/heads/main', 'refs/heads/develop'), ('schedule', 'workflow_dispatch', 'push', 'pull_request', 'workflow_run')):
            value = expression.replace('vars.RELEASE_ENABLED', repr(enabled)).replace('github.ref', repr(ref)).replace('github.event_name', repr(event)).replace('inputs.operation', repr('release')).replace('&&', ' and ').replace('||', ' or ')
            self.assertEqual(eval(value, {'__builtins__': {}}), ref == 'refs/heads/main' and event in ('schedule', 'workflow_dispatch'))
        self.assertEqual(workflow['permissions'], {'actions': 'read', 'contents': 'read'})
        self.assertEqual(workflow['concurrency'], {'group': 'release-main', 'cancel-in-progress': False})
        self.assertEqual(workflow['jobs']['publish']['needs'], ['verify', 'recovery-input'])
        for name in ('publish', 'publish-pypi', 'publish-plugin-marketplace'):
            text = str(workflow['jobs'][name])
            self.assertNotIn('python -m build', text)
            self.assertNotIn('set_package_version', text)
            self.assertNotIn('artifact-name:', text)

    def test_immutable_id_downloads_restore_directly_to_the_checked_path(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
        restored = []
        for name in ('publish', 'publish-pypi', 'publish-plugin-marketplace'):
            step, = [step for step in workflow['jobs'][name]['steps'] if step.get('uses') == 'actions/download-artifact@v4']
            self.assertTrue(step['with'].get('merge-multiple'), name)
            restored.append(step['with']['path'])
        self.assertEqual(restored, ['dist', 'verified', 'dist'])

    def test_pypi_retry_validates_before_staging_and_reads_back_even_after_upload_failure(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
        steps = workflow['jobs']['publish-pypi']['steps']
        stage, = [step for step in steps if step.get('id') == 'stage']
        self.assertIn('pypi_reconcile stage --directory verified', stage['run'])
        self.assertIn('check-main.sh', stage['run'])
        upload, = [step for step in steps if step.get('uses', '').startswith('pypa/')]
        self.assertEqual(upload['if'], "steps.stage.outputs.missing == 'true'")
        self.assertNotIn('skip-existing', upload.get('with', {}))
        confirm, = [step for step in steps if 'pypi_reconcile confirm' in step.get('run', '')]
        self.assertEqual(confirm['if'], "always() && steps.stage.outcome == 'success'")
        receipt, = [step for step in steps if step.get('uses') == 'actions/upload-artifact@v4']
        self.assertIn('github.run_attempt', receipt['with']['name'])
        self.assertEqual(receipt['if'], 'always()')

    def test_homebrew_executes_only_the_immutable_trusted_workflow_snapshot(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/homebrew.yml').read_text())
        self.assertEqual(workflow['env']['EXPECTED_SOURCE_SHA'], '${{ inputs.source_sha }}')
        for name, job in workflow['jobs'].items():
            for step in job['steps']:
                if step.get('uses') == 'actions/checkout@v4' and not step['with'].get('repository'):
                    self.assertEqual(step['with']['ref'], '${{ github.workflow_sha }}', name)
        helper = (ROOT / '.github/actions/setup-homebrew-helper/action.yml').read_text()
        self.assertNotIn('pip install .', helper)
        self.assertIn('--only-binary=:all:', helper)


class ReleaseOutcomeV2Tests(unittest.TestCase):
    def test_full_rerun_stops_before_analysis_and_product_builds(self):
        import os

        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
        steps = workflow['jobs']['verify']['steps']
        guard, = [step for step in steps if step.get('name') == 'Reject full release reruns before analysis or builds']
        self.assertLess(steps.index(guard), next(i for i, step in enumerate(steps) if step.get('id') == 'plan'))
        result = subprocess.run(['bash', '-e', '-c', guard['run']], env={**os.environ,
            'GITHUB_RUN_ATTEMPT': '2', 'GITHUB_SERVER_URL': 'https://github.com',
            'GITHUB_REPOSITORY': 'example/fixture', 'GITHUB_RUN_ID': '123'}, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('original', result.stdout.lower())
        self.assertIn('recover', result.stdout.lower())

    def test_final_summary_uses_every_retained_producer_id_and_read_only_authority(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
        self.assertEqual(workflow['name'], 'Release')
        self.assertIn('Recover release', workflow['run-name'])
        result = workflow['jobs']['result']
        self.assertEqual(result['permissions'], {'contents': 'read', 'actions': 'read'})
        downloads = [step['with'] for step in result['steps'] if step.get('uses') == 'actions/download-artifact@v4']
        self.assertEqual(len(downloads), 5)
        for download in downloads:
            self.assertIn('artifact-ids', download)
            self.assertTrue(download['merge-multiple'])
            self.assertNotIn('name', download)
        text = str(downloads)
        for producer in ['verify.outputs.analysis_artifact_id', 'verify.outputs.artifact_id',
                         'publish-pypi.outputs.receipt_artifact_id', 'publish-homebrew.outputs.receipt_artifact_id',
                         'publish-plugin-marketplace.outputs.receipt_artifact_id']:
            self.assertIn(producer, text)
