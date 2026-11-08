"""Old payload wheels must never supply credentialed release helper runtime code."""
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TrustedHelperTests(unittest.TestCase):
    def test_payload_wheel_canary_is_not_executed_by_current_helper(self):
        import yaml
        action = yaml.safe_load((ROOT / '.github/actions/setup-homebrew-helper/action.yml').read_text())
        script = action['runs']['steps'][-1]['run']
        self.assertIn('PYTHONPATH=$PWD/src', script)
        self.assertNotIn('gh-address-cr==', script)
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / 'old-payload.whl'
            with zipfile.ZipFile(wheel, 'w') as payload:
                payload.writestr('gh_address_cr/__init__.py', "raise RuntimeError('OLD_PAYLOAD_EXECUTED')")
            control = subprocess.run([sys.executable, '-c', 'import gh_address_cr'],
                                     cwd=temporary, env={**os.environ, 'PYTHONPATH': str(wheel)},
                                     text=True, capture_output=True)
            self.assertNotEqual(control.returncode, 0)
            self.assertIn('OLD_PAYLOAD_EXECUTED', control.stderr)
            env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src') + os.pathsep + str(wheel)}
            result = subprocess.run([sys.executable, '-c',
                                     'from scripts.release import recovery; import gh_address_cr; print(gh_address_cr.__file__)'],
                                    cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(ROOT / 'src'), result.stdout)

    def test_credentialed_jobs_never_install_product_wheels(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
        for name in ['publish', 'publish-pypi', 'publish-plugin-marketplace', 'recovery-input']:
            job = workflow['jobs'][name]
            self.assertIn('setup-homebrew-helper', str(job))
            for step in job['steps']:
                self.assertNotRegex(step.get('run', ''), r'pip install.*(?:dist|verified)/\*\.whl')
