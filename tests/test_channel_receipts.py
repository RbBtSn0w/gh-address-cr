"""Remote channel receipts are exact-byte observations, not publisher job results."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.release import homebrew_release, plugin_release


class ChannelReceiptTests(unittest.TestCase):
    def test_homebrew_remote_formula_bytes_and_commit_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'gh-address-cr.rb').write_bytes(b'formula')
            (root / 'publication.json').write_text(json.dumps({'targets': list(homebrew_release.shared.TARGETS)}))
            payload = {'version': '1.2.3', 'commit': 'a' * 40}
            def command(args, **_kwargs):
                value = 'b' * 40 + '\n' if 'rev-parse' in args else 'formula' if 'show' in args else ''
                return SimpleNamespace(stdout=value, returncode=0)
            with patch.object(homebrew_release, 'load_snapshot', return_value=(payload, root / 'gh-address-cr.rb')), patch.object(homebrew_release.shared, 'command', side_effect=command):
                receipt = homebrew_release.publication_receipt(root, root / 'tap')
            self.assertEqual(receipt['status'], 'completed')
            self.assertEqual(receipt['candidate_sha'], payload['commit'])
            self.assertEqual(receipt['remote_id'], 'b' * 40)
            self.assertEqual(len(receipt['bottle_targets']), 4)
            with patch.object(homebrew_release, 'load_snapshot', return_value=(payload, root / 'gh-address-cr.rb')), patch.object(homebrew_release.shared, 'command', return_value=SimpleNamespace(stdout='different', returncode=0)):
                with self.assertRaises(ValueError):
                    homebrew_release.publication_receipt(root, root / 'tap')

    def test_marketplace_receipt_requires_fresh_remote_snapshot_readback(self):
        bundle = SimpleNamespace(receipt={'source_commit': 'a' * 40, 'version': '1.2.3'})
        with patch.object(plugin_release, 'load_bundle', return_value=bundle), patch.object(plugin_release, 'verify_remote') as verify:
            result = plugin_release.publication_receipt(Path('fixture'), '1.2.3', {'status': 'published', 'commit': 'b' * 40})
            self.assertEqual(result['status'], 'completed')
            verify.assert_called_once_with(bundle, plugin_release.REMOTE, 'b' * 40)
        with patch.object(plugin_release, 'load_bundle', return_value=bundle), patch.object(plugin_release, 'verify_remote') as verify:
            result = plugin_release.publication_receipt(Path('fixture'), '1.2.3', {'status': 'superseded', 'commit': 'b' * 40})
            self.assertEqual(result['status'], 'unknown')
            verify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
