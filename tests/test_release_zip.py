"""Validate archive metadata before any Actions artifact extraction."""
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path


class ArchiveSafetyTests(unittest.TestCase):
    def test_rejects_traversal_aliases_duplicate_paths_and_symlinks(self):
        from scripts.release.check_artifact_zip import validate
        for name in ['../escape', '/absolute', 'a/../escape', 'a\\escape', './plan.json']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / 'test.zip'
                with zipfile.ZipFile(archive, 'w') as payload:
                    payload.writestr(name, 'untrusted')
                with self.assertRaises(ValueError):
                    validate(archive)
        for entries in [('plan.json', 'PLAN.JSON'), ('plan.json', 'plan.json')]:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / 'test.zip'
                with zipfile.ZipFile(archive, 'w') as payload:
                    for name in entries:
                        payload.writestr(name, 'untrusted')
                with self.assertRaises(ValueError):
                    validate(archive)
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'test.zip'
            with zipfile.ZipFile(archive, 'w') as payload:
                link = zipfile.ZipInfo('link')
                link.create_system = 3
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                payload.writestr(link, '../target')
            with self.assertRaises(ValueError):
                validate(archive)

    def test_accepts_regular_nested_verified_payload(self):
        from scripts.release.check_artifact_zip import validate
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'test.zip'
            with zipfile.ZipFile(archive, 'w') as payload:
                payload.writestr('plan.json', '{}')
                payload.writestr('plugin-release/plugin.zip', 'sealed')
            validate(archive)
