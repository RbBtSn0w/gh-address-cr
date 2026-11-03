import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.release import plugin_release as release
from tests.helpers import ROOT


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.fsmonitor=false', '-C', str(root), *args], text=True).strip()


class PluginReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        git(self.source, 'init', '-q')
        git(self.source, 'config', 'user.name', 'Test')
        git(self.source, 'config', 'user.email', 'test@example.invalid')
        for name in ['skill', '.agents/plugins', 'assets/plugin']:
            import shutil
            shutil.copytree(ROOT / name, self.source / name)
        for name in ['LICENSE', 'pyproject.toml', 'scripts/build_plugin_payload.py']:
            (self.source / name).parent.mkdir(parents=True, exist_ok=True)
            (self.source / name).write_bytes((ROOT / name).read_bytes())
        text = (self.source / 'pyproject.toml').read_text()
        import re
        (self.source / 'pyproject.toml').write_text(re.sub(r'^version = ".*"$', 'version = "1.0.0"', text, flags=re.M))
        git(self.source, 'add', '.')
        git(self.source, 'commit', '-qm', 'fixture')
        git(self.source, 'tag', 'v1.0.0')
        self.bundle = self.root / 'bundle'
        release.prepare(self.bundle, '1.0.0', source=self.source, run_url='https://github.com/RbBtSn0w/gh-address-cr/actions/runs/1')
        self.remote = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '-q', str(self.remote)], check=True)

    def test_bundle_is_source_bound_and_tampering_fails(self):
        bundle = release.load_bundle(self.bundle, '1.0.0')
        release.verify_source(bundle, self.source)
        archive = self.bundle / 'gh-address-cr-1.0.0.zip'
        archive.write_bytes(archive.read_bytes() + b'tamper')
        with self.assertRaises(ValueError):
            release.load_bundle(self.bundle, '1.0.0')

    def test_git_publish_creates_complete_snapshot_and_is_idempotent(self):
        bundle = release.load_bundle(self.bundle, '1.0.0')
        first = release.publish_git(bundle, str(self.remote))
        head = git(self.remote, 'rev-parse', 'refs/heads/marketplace')
        self.assertEqual(first['commit'], head)
        receipt = json.loads(git(self.remote, 'show', f'{head}:publication.json'))
        self.assertEqual(receipt['source_commit'], git(self.source, 'rev-parse', 'HEAD'))
        release.verify_remote(bundle, str(self.remote), head)
        second = release.publish_git(bundle, str(self.remote))
        self.assertEqual(second['status'], 'unchanged')
        self.assertEqual(git(self.remote, 'rev-parse', 'refs/heads/marketplace'), head)

    def test_publication_policy(self):
        candidate = release.load_bundle(self.bundle, '1.0.0').receipt
        self.assertEqual(release.publication_policy(None, candidate), 'publish')
        self.assertEqual(release.publication_policy(candidate, candidate), 'unchanged')
        newer = dict(candidate, version='1.0.1', source_tag='v1.0.1', archive=dict(candidate['archive'], name='gh-address-cr-1.0.1.zip'))
        self.assertEqual(release.publication_policy(candidate, newer), 'publish')
        self.assertEqual(release.publication_policy(newer, candidate), 'superseded')
        with self.assertRaises(ValueError):
            release.publication_policy(dict(candidate, source_commit='f' * 40), candidate)
        with self.assertRaises(ValueError):
            release.publication_policy({'schema_version': 'unknown'}, candidate)

    def test_same_version_remote_tree_divergence_is_not_hidden_by_receipt(self):
        bundle = release.load_bundle(self.bundle, '1.0.0')
        release.publish_git(bundle, str(self.remote))
        clone = self.root / 'clone'
        subprocess.run(['git', 'clone', '-q', '--branch', 'marketplace', str(self.remote), str(clone)], check=True)
        git(clone, 'config', 'user.name', 'Test')
        git(clone, 'config', 'user.email', 'test@example.invalid')
        (clone / 'unexpected.txt').write_text('corruption')
        git(clone, 'add', '.')
        git(clone, 'commit', '-qm', 'diverge')
        git(clone, 'push', '-q', 'origin', 'marketplace')
        with self.assertRaises(ValueError):
            release.publish_git(bundle, str(self.remote))

    def test_uncertain_asset_upload_reconciles_existing_bytes(self):
        assets = release.PluginAssets('1.0.0')
        archive = self.bundle / 'gh-address-cr-1.0.0.zip'
        def download(name, target):
            target.mkdir(parents=True, exist_ok=True)
            result = target / name
            result.write_bytes(archive.read_bytes())
            return result
        with patch.object(assets, 'names', side_effect=[set(), {archive.name}]), patch.object(assets, 'download', side_effect=download), patch.object(release.shared, 'command', side_effect=ValueError('uncertain')):
            assets.upload_verified(archive)

    def test_recovery_rejects_missing_assets(self):
        with patch.object(release, 'require_release'), patch.object(release.PluginAssets, 'names', return_value=set()):
            with self.assertRaisesRegex(ValueError, 'missing'):
                release.recover(self.root / 'recovery', '1.0.0')

    def test_push_response_loss_is_reconciled_without_duplicate_commit(self):
        bundle = release.load_bundle(self.bundle, '1.0.0')
        original = release.shared.command
        lost = []
        def command(argv, **kwargs):
            result = original(argv, **kwargs)
            if argv[:2] == ['git', 'push'] and not lost:
                lost.append(True)
                return subprocess.CompletedProcess(argv, 1, '', 'response lost')
            return result
        with patch.object(release.shared, 'command', side_effect=command):
            result = release.publish_git(bundle, str(self.remote))
        self.assertEqual(result['status'], 'unchanged')
        self.assertEqual(git(self.remote, 'rev-list', '--count', 'marketplace'), '1')

    def test_source_binding_rejects_changed_tag(self):
        bundle = release.load_bundle(self.bundle, '1.0.0')
        (self.source / 'LICENSE').write_text('different')
        git(self.source, 'add', '.')
        git(self.source, 'commit', '-qm', 'change')
        git(self.source, 'tag', '-f', 'v1.0.0')
        with self.assertRaisesRegex(ValueError, 'source tag'):
            release.verify_source(bundle, self.source)

    def test_conflicting_asset_bytes_are_never_replaced(self):
        assets = release.PluginAssets('1.0.0')
        archive = self.bundle / 'gh-address-cr-1.0.0.zip'
        def download(name, target):
            target.mkdir(parents=True, exist_ok=True)
            result = target / name
            result.write_bytes(b'conflict')
            return result
        with patch.object(assets, 'names', return_value={archive.name}), patch.object(assets, 'download', side_effect=download):
            with self.assertRaisesRegex(ValueError, 'different bytes'):
                assets.upload_verified(archive)

    def test_push_failure_is_bounded_and_does_not_publish(self):
        bundle = release.load_bundle(self.bundle, '1.0.0')
        original = release.shared.command
        pushes = []
        def command(argv, **kwargs):
            if argv[:2] == ['git', 'push']:
                pushes.append(argv)
                return subprocess.CompletedProcess(argv, 1, '', 'blocked')
            return original(argv, **kwargs)
        with patch.object(release.shared, 'command', side_effect=command):
            with self.assertRaisesRegex(ValueError, 'three reconciled attempts'):
                release.publish_git(bundle, str(self.remote))
        self.assertEqual(len(pushes), 3)
        self.assertEqual(git(self.remote, 'for-each-ref'), '')

    def test_remote_readback_failure_cannot_report_success(self):
        bundle = release.load_bundle(self.bundle, '1.0.0')
        with patch.object(release, 'verify_remote', side_effect=ValueError('readback mismatch')):
            with self.assertRaisesRegex(ValueError, 'readback mismatch'):
                release.publish_git(bundle, str(self.remote))

    def test_git_auth_is_scoped_to_github_without_secret_in_argv(self):
        with patch.dict('os.environ', {'GH_TOKEN': 'fixture-token'}, clear=True):
            env = release.git_environment()
        self.assertEqual(env['GIT_CONFIG_KEY_0'], 'http.https://github.com/.extraheader')
        self.assertTrue(env['GIT_CONFIG_VALUE_0'].startswith('AUTHORIZATION: basic '))
        self.assertEqual(env['GIT_CONFIG_COUNT'], '1')

    def test_rejects_nonstable_and_draft_releases(self):
        with self.assertRaises(ValueError):
            release.asset_names('1.0.0-beta.1')
        with patch.object(release.shared, 'github_json', return_value={'tag_name': 'v1.0.0', 'draft': True, 'prerelease': False}):
            with self.assertRaisesRegex(ValueError, 'stable GitHub Release'):
                release.require_release('1.0.0')


    def test_recomputed_receipt_cannot_hide_generated_asset_tampering(self):
        bundle = release.load_bundle(self.bundle, '1.0.0')
        bundle.payload['assets/icon.png'] = b'altered image'
        bundle.receipt['files']['assets/icon.png'] = release.sha(b'altered image')
        with self.assertRaisesRegex(ValueError, 'generated'):
            release.verify_source(bundle, self.source)

    def test_publication_and_recovery_never_execute_a_source_builder(self):
        original = release.shared.command
        def command(argv, **kwargs):
            if Path(argv[0]).name.startswith('python') and any('build_plugin_payload.py' in str(part) for part in argv):
                raise AssertionError('source builder executed under publisher authority')
            return original(argv, **kwargs)
        with patch.object(release.shared, 'command', side_effect=command), patch.object(release, 'require_release'), patch.object(release.PluginAssets, 'upload_verified'), patch.object(release, 'publish_git', return_value={'status': 'published'}):
            release.publish(self.bundle, '1.0.0', source=self.source)
            def download(name, directory):
                directory.mkdir(parents=True, exist_ok=True)
                (directory / name).write_bytes((self.bundle / name).read_bytes())
            with patch.object(release.PluginAssets, 'names', return_value=set(release.asset_names('1.0.0'))), patch.object(release.PluginAssets, 'download', side_effect=download):
                release.recover(self.root / 'recovery', '1.0.0', source=self.source)

    def test_generation_comparison_is_required_in_readonly_preparation(self):
        with patch('scripts.release.plugin_bundle.verify_generated', side_effect=ValueError('readonly generation comparison')):
            with self.assertRaisesRegex(ValueError, 'readonly generation'):
                release.prepare(self.root / 'another-bundle', '1.0.0', source=self.source, run_url='https://github.com/RbBtSn0w/gh-address-cr/actions/runs/1')
