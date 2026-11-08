"""Existing asset conflicts must be observed before any missing asset is uploaded."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.release import recovery


class AssetPreflightTests(unittest.TestCase):
    def test_later_conflict_blocks_an_earlier_missing_asset_without_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'missing.whl').write_bytes(b'original missing')
            (directory / 'conflict.tar.gz').write_bytes(b'original archive')
            release = {'id': 1, 'tag_name': 'v1.2.3', 'body': 'Original notes',
                       'prerelease': False, 'draft': False,
                       'assets': [{'name': 'conflict.tar.gz', 'id': 7}]}
            fresh = {**release, 'assets': [*release['assets'], {'name': 'missing.whl', 'id': 8}]}
            def download(_repository, asset_id):
                return b'original missing' if asset_id == 8 else b'conflicting remote archive'
            with patch.object(recovery, 'command', return_value=json.dumps(fresh)) as mutation, \
                    patch.object(recovery, 'download', side_effect=download):
                with self.assertRaisesRegex(ValueError, 'differs'):
                    recovery.reconcile_assets('example/repo', release, directory,
                                              ['missing.whl', 'conflict.tar.gz'], 'Original notes')
                self.assertEqual([call for call in mutation.call_args_list
                                  if call.args[0][:3] == ['gh', 'release', 'upload']], [])
