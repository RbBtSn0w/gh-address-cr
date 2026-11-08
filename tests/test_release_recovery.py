"""Release-only recovery must trust sealed candidate identity after main advances."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class RecoveryTests(unittest.TestCase):
    def test_recovery_uses_original_tag_and_never_live_main(self):
        from scripts.release.recovery import verify_tag
        candidate = 'a' * 40
        with patch('scripts.release.recovery.command', return_value=candidate + '\trefs/tags/v1.2.3\n') as command:
            verify_tag('RbBtSn0w/gh-address-cr', 'v1.2.3', candidate)
        self.assertNotIn('main', str(command.call_args))
        with patch('scripts.release.recovery.command', return_value='b' * 40 + '\trefs/tags/v1.2.3\n'):
            with self.assertRaises(ValueError):
                verify_tag('RbBtSn0w/gh-address-cr', 'v1.2.3', candidate)

    def test_matching_asset_is_not_uploaded_and_conflict_fails(self):
        from scripts.release.recovery import reconcile_assets
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.whl').write_bytes(b'original')
            release = {'id': 4, 'tag_name': 'v1.2.3', 'body': 'sealed notes', 'prerelease': False,
                       'assets': [{'id': 7, 'name': 'package.whl'}]}
            with patch('scripts.release.recovery.download', return_value=b'original'), patch('scripts.release.recovery.command') as command:
                reconcile_assets('owner/repo', release, root, ['package.whl'], 'sealed notes')
                command.assert_not_called()
            with patch('scripts.release.recovery.download', return_value=b'changed'):
                with self.assertRaises(ValueError):
                    reconcile_assets('owner/repo', release, root, ['package.whl'], 'sealed notes')

    def test_verify_job_is_not_activation_gated_and_recovery_is_explicit(self):
        import yaml
        workflow = yaml.safe_load(Path('.github/workflows/release.yml').read_text())
        self.assertNotIn('RELEASE_ENABLED', workflow['jobs']['verify']['if'])
        self.assertIn('recover', json.dumps(workflow))
        self.assertIn('recovery-source.mjs', json.dumps(workflow))
        self.assertIn('release-result.json', json.dumps(workflow))

    def test_homebrew_recovery_requires_original_bottle_bundle(self):
        from scripts.release import homebrew_release
        with tempfile.TemporaryDirectory() as temporary, \
                patch('scripts.release.homebrew_release.load_snapshot', return_value=({'version': '1.2.3'}, '')), \
                patch('scripts.release.homebrew_release.shared.ReleaseAssets') as assets, \
                patch('scripts.release.homebrew_release.shared.formula_text', side_effect=RuntimeError('unexpected rebuild')), \
                patch.dict('os.environ', {'RELEASE_OPERATION': 'recover'}):
            assets.return_value.names.return_value = set()
            with self.assertRaisesRegex(ValueError, 'recovery never builds'):
                homebrew_release.build(Path(temporary), Path(temporary), 'macos-15', 0)

    def test_homebrew_recovery_requires_original_resource_snapshot(self):
        from scripts.release import homebrew_release
        with tempfile.TemporaryDirectory() as temporary, \
                patch('scripts.release.homebrew_release.stable_source', return_value=('a' * 40, 'url', 'digest')), \
                patch('scripts.release.homebrew_release.shared.ReleaseAssets') as assets, \
                patch('scripts.release.homebrew_release.resolve_formula', side_effect=RuntimeError('unexpected resource resolution')), \
                patch.dict('os.environ', {'RELEASE_OPERATION': 'recover'}):
            assets.return_value.names.return_value = set()
            with self.assertRaisesRegex(ValueError, 'original resource snapshot'):
                homebrew_release.prepare(Path(temporary), '1.2.3')

    def test_matching_draft_finishes_after_asset_verification_without_retag_or_reupload(self):
        from scripts.release.recovery import recover
        candidate = 'a' * 40
        draft = {'id': 4, 'tag_name': 'v1.2.3', 'body': 'sealed notes', 'draft': True, 'prerelease': False,
                 'assets': [{'id': 7, 'name': 'package.whl'}]}
        stable = {**draft, 'draft': False}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.whl').write_bytes(b'original')
            responses = [candidate + '\trefs/tags/v1.2.3', json.dumps([[draft]]), json.dumps(draft), '', json.dumps(stable)]
            with patch('scripts.release.recovery.command', side_effect=responses) as command, \
                    patch('scripts.release.recovery.download', return_value=b'original'):
                recover('owner/repo', root, {'candidate': candidate, 'version': '1.2.3', 'notes': 'sealed notes'}, ['package.whl'])
            calls = [call.args[0] for call in command.call_args_list]
            self.assertEqual(calls[3], ['gh', 'release', 'edit', 'v1.2.3', '--repo', 'owner/repo', '--draft=false', '--latest=false'])
            self.assertFalse(any('create' in call or 'upload' in call for call in calls))

    def test_missing_release_retrieves_created_draft_from_paginated_list(self):
        from scripts.release.recovery import recover
        candidate = 'a' * 40
        draft = {'id': 4, 'tag_name': 'v1.2.3', 'body': 'sealed notes', 'draft': True, 'prerelease': False,
                 'assets': [{'id': 7, 'name': 'package.whl'}]}
        published = False
        listed = 0

        def response(arguments):
            nonlocal published, listed
            if arguments[0] == 'git':
                return candidate + '\trefs/tags/v1.2.3'
            if '--slurp' in arguments:
                listed += 1
                return json.dumps([[] if listed == 1 else [draft]])
            if arguments[1:3] == ['release', 'create']:
                self.assertIn('--latest=false', arguments)
                return ''
            if arguments[1:3] == ['release', 'edit']:
                self.assertIn('--latest=false', arguments)
                published = True
                return ''
            if arguments[-1].endswith('/releases/4'):
                return json.dumps(draft)
            self.assertTrue(published, 'GetReleaseByTag cannot retrieve a draft')
            return json.dumps({**draft, 'draft': False})

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'payload'
            root.mkdir()
            (root / 'package.whl').write_bytes(b'original')
            with patch('scripts.release.recovery.command', side_effect=response), \
                    patch('scripts.release.recovery.download', return_value=b'original'):
                recover('owner/repo', root, {'candidate': candidate, 'version': '1.2.3', 'notes': 'sealed notes'}, ['package.whl'])
            self.assertEqual((root.parent / 'original-release-notes.md').read_text(), 'sealed notes')
            self.assertEqual(listed, 2)

_MISSING_NOTES = object()


class ReleaseNotesConsistencyTests(unittest.TestCase):
    def exercise(self, *, draft=True, notes='sealed notes', body='sealed notes',
                 absent=False, missing_asset=False, phase=None, changes=None):
        from scripts.release.recovery import recover
        candidate = 'a' * 40
        current = {'id': 4, 'tag_name': 'v1.2.3', 'body': body, 'draft': draft,
                   'prerelease': False, 'assets': [] if missing_asset else [{'id': 7, 'name': 'package.whl'}]}
        if body is _MISSING_NOTES:
            current.pop('body')
        mutations = []
        created_notes = []
        present = not absent

        def response(arguments):
            nonlocal present
            if arguments[0] == 'git':
                return candidate + '\trefs/tags/v1.2.3'
            if '--slurp' in arguments:
                return json.dumps([[current] if present else []])
            if arguments[1:3] == ['release', 'create']:
                mutations.append('create')
                original = Path(arguments[arguments.index('--notes-file') + 1]).read_text(encoding='utf-8')
                created_notes.append(original)
                current.update(body=original, draft=True)
                present = True
                return ''
            if arguments[1:3] == ['release', 'upload']:
                mutations.append('upload')
                current['assets'] = [{'id': 7, 'name': 'package.whl'}]
                return ''
            if arguments[1:3] == ['release', 'edit']:
                self.assertFalse(any(argument.startswith('--notes') for argument in arguments))
                mutations.append('publish')
                current['draft'] = False
                return ''
            if arguments[:2] == ['gh', 'api']:
                observed = dict(current)
                by_id = arguments[-1].endswith('/releases/4')
                by_tag = arguments[-1].endswith('/releases/tags/v1.2.3')
                if ((phase == 'after-upload' and by_id and 'upload' in mutations)
                        or (phase == 'before-publish' and by_id and 'upload' not in mutations)
                        or (phase == 'final' and by_tag)):
                    observed.update(changes or {'body': 'changed externally'})
                return json.dumps(observed)
            raise AssertionError(f'unexpected synthetic command: {arguments}')

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'payload'
            root.mkdir()
            (root / 'package.whl').write_bytes(b'original')
            plan = {'candidate': candidate, 'version': '1.2.3'}
            if notes is not _MISSING_NOTES:
                plan['notes'] = notes
            error = None
            with patch('scripts.release.recovery.command', side_effect=response), \
                    patch('scripts.release.recovery.download', return_value=b'original'):
                try:
                    recover('owner/repo', root, plan, ['package.whl'])
                except ValueError as failure:
                    error = failure
        return error, mutations, created_notes

    def test_existing_notes_conflicts_are_rejected_before_any_mutation(self):
        for draft in (True, False):
            for body in ('conflicting notes', None, _MISSING_NOTES):
                with self.subTest(draft=draft, body=body):
                    error, mutations, _ = self.exercise(draft=draft, body=body, missing_asset=True)
                    self.assertIsNotNone(error)
                    self.assertIn('notes', str(error))
                    self.assertEqual(mutations, [])

    def test_sealed_notes_must_be_present_as_a_string_before_any_mutation(self):
        for notes in (_MISSING_NOTES, None, 42, False, {}):
            for absent in (True, False):
                with self.subTest(notes=notes, absent=absent):
                    error, mutations, _ = self.exercise(notes=notes, absent=absent)
                    self.assertIsNotNone(error)
                    self.assertIn('notes', str(error))
                    self.assertEqual(mutations, [])

    def test_matching_notes_allow_idempotent_stable_and_draft_completion(self):
        for draft in (True, False):
            for notes in ('sealed notes', ''):
                with self.subTest(draft=draft, notes=notes):
                    error, mutations, _ = self.exercise(draft=draft, notes=notes, body=notes)
                    self.assertIsNone(error)
                    self.assertEqual(mutations, ['publish'] if draft else [])
        error, mutations, _ = self.exercise(notes='', body=None)
        self.assertIsNotNone(error)
        self.assertEqual(mutations, [])

    def test_absent_release_uses_exact_original_notes_including_empty_string(self):
        for notes in ('Original notes\n\nUnicode: 原文\n', ''):
            with self.subTest(notes=notes):
                error, mutations, created = self.exercise(absent=True, notes=notes)
                self.assertIsNone(error)
                self.assertEqual(created, [notes])
                self.assertEqual(mutations, ['create', 'publish'])

    def test_conflict_read_after_upload_or_before_publish_never_publishes(self):
        for phase in ('after-upload', 'before-publish'):
            for changes in ({'body': 'changed externally'}, {'tag_name': 'v9.9.9'}, {'id': 99}):
                with self.subTest(phase=phase, changes=changes):
                    error, mutations, _ = self.exercise(missing_asset=phase == 'after-upload',
                                                       phase=phase, changes=changes)
                    self.assertIsNotNone(error)
                    self.assertEqual(mutations, ['upload'] if phase == 'after-upload' else [])

    def test_final_readback_must_keep_identity_and_original_notes(self):
        for draft in (True, False):
            for changes in ({'body': 'changed externally'}, {'body': None}, {'tag_name': 'v9.9.9'}, {'id': 99}):
                with self.subTest(draft=draft, changes=changes):
                    error, mutations, _ = self.exercise(draft=draft, phase='final', changes=changes)
                    self.assertIsNotNone(error)
                    self.assertEqual(mutations, ['publish'] if draft else [])
