import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.release import plugin_marketplace_smoke as smoke
from tests.helpers import ROOT


class MarketplaceSmokeTests(unittest.TestCase):
    def test_existing_profile_is_never_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / '.codex').mkdir()
            config = home / '.codex/config.toml'
            config.write_text('preserved')
            with patch.dict('os.environ', {'GITHUB_ACTIONS': 'true'}), patch.object(Path, 'home', return_value=home):
                with self.assertRaisesRegex(ValueError, 'already populated'):
                    smoke.require_disposable_profile()
            self.assertEqual(config.read_text(), 'preserved')

    def test_developer_environment_is_rejected(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'disposable'):
                smoke.require_disposable_profile()

    def test_newer_cached_version_does_not_prove_active_update(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            cache = home / '.codex/plugins/cache/gh-address-cr-community/gh-address-cr'
            for version in ['1.0.0', '1.0.1']:
                path = cache / version
                path.mkdir(parents=True)
                (path / 'plugin.json').write_text(json.dumps({'version': version}))
                shutil.copytree(ROOT / 'skill', path / 'skills/gh-address-cr')
            output = {'installed': [{'name': 'gh-address-cr', 'marketplaceName': 'gh-address-cr-community',
                                     'installed': True, 'enabled': True, 'version': '1.0.0'}]}
            result = subprocess.CompletedProcess([], 0, json.dumps(output), '')
            with patch.object(Path, 'home', return_value=home), patch.object(smoke.shared, 'command', return_value=result):
                self.assertEqual(smoke.installed_version('codex'), '1.0.0')
                (cache / '1.0.0/skills/gh-address-cr/SKILL.md').write_text('corruption')
                with self.assertRaisesRegex(ValueError, 'active installed skill'):
                    smoke.installed_version('codex')
