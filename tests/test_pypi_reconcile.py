"""Immutable PyPI reconciliation without uploads or external reads."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.release import pypi_reconcile as pypi
from scripts.release.handoff import inventory


class PyPIReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.verified = self.root / 'verified'
        self.verified.mkdir()
        self.candidate = 'a' * 40
        self.wheel = 'gh_address_cr-1.2.3-py3-none-any.whl'
        self.sdist = 'gh_address_cr-1.2.3.tar.gz'
        (self.verified / self.wheel).write_bytes(b'wheel')
        (self.verified / self.sdist).write_bytes(b'sdist')
        (self.verified / 'plan.json').write_text(json.dumps({'completed': True, 'candidate': self.candidate, 'version': '1.2.3'}))
        (self.verified / 'handoff.json').write_text(json.dumps({'candidate': self.candidate, 'files': inventory(self.verified)}))
        self.receipt = self.root / 'receipt.json'

    def remote(self, names):
        return {'info': {'version': '1.2.3'}, 'urls': [
            {'filename': name, 'digests': {'sha256': hashlib.sha256((self.verified / name).read_bytes()).hexdigest()}}
            for name in names]}

    def stage(self, remote):
        with patch.object(pypi, 'read_version', return_value=remote):
            return pypi.reconcile(self.verified, self.candidate, self.root / 'missing', self.receipt)

    def test_partial_upload_stages_only_missing_bytes_and_repeat_is_noop(self):
        self.assertTrue(self.stage(self.remote([self.wheel])))
        self.assertEqual({p.name for p in (self.root / 'missing').iterdir()}, {self.sdist})
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual(receipt['files'][self.wheel]['status'], 'already-present')
        self.assertEqual(receipt['files'][self.sdist]['status'], 'missing')
        with patch.object(pypi, 'read_version', return_value=self.remote([self.wheel, self.sdist])):
            self.assertFalse(pypi.reconcile(self.verified, self.candidate, self.root / 'repeat', self.receipt))
            pypi.reconcile(self.verified, self.candidate, None, self.receipt)
        self.assertEqual(json.loads(self.receipt.read_text())['files'][self.sdist]['status'], 'verified')
        confirmed = json.loads(self.receipt.read_text())
        self.assertIn('observed_at', confirmed)
        self.assertEqual(confirmed['expected_files'], {
            name: entry['sha256'] for name, entry in confirmed['files'].items()})

    def test_wrong_existing_bytes_and_missing_confirmation_fail(self):
        remote = self.remote([self.wheel])
        remote['urls'][0]['digests']['sha256'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'different bytes'):
            self.stage(remote)
        self.assertFalse((self.root / 'missing').exists())
        with patch.object(pypi, 'read_version', return_value=self.remote([self.wheel])):
            with self.assertRaisesRegex(ValueError, 'missing'):
                pypi.reconcile(self.verified, self.candidate, None, self.receipt)

    def test_handoff_is_fully_verified_before_network_or_staging(self):
        (self.verified / self.sdist).write_bytes(b'changed')
        with patch.object(pypi, 'read_version') as read:
            with self.assertRaisesRegex(ValueError, 'checksum'):
                pypi.reconcile(self.verified, self.candidate, self.root / 'missing', self.receipt)
            read.assert_not_called()

    def test_reads_fail_closed_except_real_404(self):
        from urllib.error import HTTPError, URLError
        for error in (HTTPError('https://pypi.org', 403, 'denied', None, None), HTTPError('https://pypi.org', 500, 'error', None, None), URLError('offline')):
            with self.subTest(error=error), patch.object(pypi, 'urlopen', side_effect=error):
                with self.assertRaises((HTTPError, URLError)):
                    pypi.read_version('1.2.3')
        with patch.object(pypi, 'urlopen', side_effect=HTTPError('https://pypi.org', 404, 'absent', None, None)):
            self.assertIsNone(pypi.read_version('1.2.3'))

    def test_absent_release_stages_both_archives_and_receipt_records_each_digest(self):
        self.assertTrue(self.stage(None))
        self.assertEqual({p.name for p in (self.root / 'missing').iterdir()}, {self.wheel, self.sdist})
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual({entry['status'] for entry in receipt['files'].values()}, {'missing'})
        for name, entry in receipt['files'].items():
            self.assertEqual(entry['sha256'], hashlib.sha256((self.verified / name).read_bytes()).hexdigest())

    def test_malformed_metadata_cannot_be_treated_as_absent(self):
        malformed = [
            {}, {'info': [], 'urls': []}, {'info': {'version': '9.9.9'}, 'urls': []},
            {'info': {'version': '1.2.3'}, 'urls': [{'filename': self.wheel, 'digests': {}}]},
            {'info': {'version': '1.2.3'}, 'urls': [{'filename': self.wheel, 'digests': []}]},
        ]
        duplicate = self.remote([self.wheel, self.wheel])
        for response in [*malformed, duplicate]:
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.stage(response)
        self.assertFalse((self.root / 'missing').exists())

    def test_failed_read_retains_unverified_receipt_and_stages_nothing(self):
        from urllib.error import URLError
        with patch.object(pypi, 'read_version', side_effect=URLError('offline')):
            with self.assertRaises(URLError):
                pypi.reconcile(self.verified, self.candidate, self.root / 'missing', self.receipt)
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual(receipt['read_error'], 'URLError')
        self.assertEqual({entry['status'] for entry in receipt['files'].values()}, {'unverified'})
        self.assertFalse((self.root / 'missing').exists())

    def test_cli_reports_missing_output_and_confirms_exact_files(self):
        import os
        import sys
        output = self.root / 'step-output'
        arguments = ['pypi_reconcile', 'stage', '--directory', str(self.verified), '--candidate', self.candidate,
                     '--output', str(self.root / 'cli-missing'), '--receipt', str(self.receipt)]
        with patch.object(sys, 'argv', arguments), patch.dict(os.environ, {'GITHUB_OUTPUT': str(output)}), patch.object(pypi, 'read_version', return_value=self.remote([self.wheel])):
            pypi.main()
        self.assertEqual(output.read_text(), 'missing=true\n')
        self.assertEqual((self.root / 'cli-missing' / self.sdist).read_bytes(), b'sdist')
        arguments = ['pypi_reconcile', 'confirm', '--directory', str(self.verified), '--candidate', self.candidate,
                     '--receipt', str(self.receipt)]
        with patch.object(sys, 'argv', arguments), patch.object(pypi, 'read_version', return_value=self.remote([self.wheel, self.sdist])):
            pypi.main()
        self.assertEqual({entry['status'] for entry in json.loads(self.receipt.read_text())['files'].values()}, {'verified'})

    def test_success_response_with_invalid_json_or_status_fails_closed(self):
        from unittest.mock import MagicMock
        for status, body in [(200, b'bad json'), (200, b'null'), (200, b'[]'), (204, b''), (200, b'x' * (8 * 1024 * 1024 + 1))]:
            response = MagicMock()
            response.__enter__.return_value = response
            response.status = status
            response.read.return_value = body
            with self.subTest(status=status, length=len(body)), patch.object(pypi, 'urlopen', return_value=response):
                with self.assertRaises(ValueError):
                    pypi.read_version('1.2.3')
