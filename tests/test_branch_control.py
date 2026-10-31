"""Guarded merge boundary contracts; no live GitHub mutation."""
import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.release import branch_control as bc

A, B, C = 'a' * 40, 'b' * 40, 'c' * 40
REPO = 'owner/project'


def pull():
    return {'number': 7, 'state': 'open', 'merged': False, 'draft': False, 'mergeable': True,
            'head': {'ref': 'develop', 'sha': B, 'repo': {'full_name': REPO}},
            'base': {'ref': 'main', 'sha': A, 'repo': {'full_name': REPO}}}


class PolicyTests(unittest.TestCase):
    def test_direction_rejects_fork_and_generic_sync(self):
        self.assertEqual(bc.direction(pull(), REPO), 'release')
        value = pull()
        value['head']['repo']['full_name'] = 'evil/project'
        with self.assertRaises(ValueError):
            bc.direction(value, REPO)
        value = pull()
        value['head']['ref'] = 'main'
        value['base']['ref'] = 'develop'
        with self.assertRaises(ValueError):
            bc.direction(value, REPO)

    def test_owned_summary_is_idempotent_and_rejects_spoofed_markers(self):
        body = 'Human description\n'
        updated = bc.replace_summary(body, 'Ready')
        self.assertTrue(updated.startswith(body))
        self.assertEqual(updated, bc.replace_summary(updated, 'Ready'))
        for invalid in (bc.START, bc.END + bc.START, bc.START + bc.START + bc.END):
            with self.assertRaises(ValueError):
                bc.replace_summary(invalid, 'Ready')

    def test_receipt_matches_run_attempt_current_base_and_real_merge(self):
        run = {'id': 10, 'run_attempt': 2, 'head_sha': B}
        receipt = {'schema_version': 'branch-validation.v1', 'repository': REPO, 'pr_number': 7,
                   'head_sha': B, 'base_sha': A, 'tested_merge_sha': C,
                   'run_id': 10, 'run_attempt': 2, 'merge_parents': [A, B]}
        commit = {'parents': [{'sha': A}, {'sha': B}]}
        bc.validate_receipt(receipt, run, pull(), REPO, commit)
        for key, value in [('base_sha', C), ('run_attempt', 1), ('pr_number', 8)]:
            invalid = {**receipt, key: value}
            with self.assertRaises(ValueError):
                bc.validate_receipt(invalid, run, pull(), REPO, commit)
        with self.assertRaises(ValueError):
            bc.validate_receipt(receipt, run, pull(), REPO, {'parents': [{'sha': B}, {'sha': A}]})

    def test_merged_summary_does_not_request_another_merge_or_claim_new_checks(self):
        data = {'status': 'merged', 'direction': 'release', 'head_sha': B, 'base_sha': A,
                'release': {'current_version': '3.21.3', 'release_type': None}, 'publication': []}
        text = bc.markdown_summary(data)
        self.assertIn('already merged', text.lower())
        self.assertIn('3.21.3', text)
        self.assertNotIn('Dispatch guarded merge', text)
        self.assertNotIn('blocked or unavailable', text)
        self.assertNotIn('Release type:** none', text)

    def test_review_projection_does_not_copy_private_runtime_artifact_paths(self):
        result = type('Result', (), {'returncode': 0, 'stdout': json.dumps({
            'status': 'PASSED', 'gate_scope': 'final', 'exit_code': 0, 'counts': {},
            'artifact_path': '/Users/private-user/state/audit.md',
            'completion_summary': {'markdown': '/Users/private-user/state/report.json'},
        })})()
        with patch.object(bc.shared, 'command', return_value=result):
            report = bc.final_gate(REPO, 7, require_checks=False)
        self.assertTrue(report['passed'])
        self.assertNotIn('/Users/', json.dumps(report))

    def test_corrupted_or_inline_gate_cannot_authorize_merge(self):
        for payload in ({}, {'status': 'PASSED', 'gate_scope': 'inline'},
                        {'status': 'FAILED', 'gate_scope': 'final'},
                        {'status': 'PASSED', 'gate_scope': 'final', 'exit_code': 5}):
            result = type('Result', (), {'returncode': 0, 'stdout': json.dumps(payload)})()
            with patch.object(bc.shared, 'command', return_value=result):
                self.assertFalse(bc.final_gate(REPO, 7, require_checks=True)['passed'])

    def test_fact_reads_do_not_require_actions_permission_on_merge_bot(self):
        response = type('Result', (), {'returncode': 0, 'stdout': json.dumps({
            'status': 'PASSED', 'gate_scope': 'final', 'exit_code': 0, 'counts': {},
        })})()
        with patch.dict('os.environ', {'GH_TOKEN': 'merge-bot', 'GH_TRUNK_READ_TOKEN': 'read-only',
                                               'GH_TRUNK_MERGE_DEADLINE_EPOCH': str(dt.datetime.now(dt.UTC).timestamp() + 400)}), \
             patch.object(bc.shared, 'command', return_value=response) as execute:
            bc.api(f'repos/{REPO}/actions/runs/10')
            self.assertEqual(execute.call_args.kwargs.get('env', {}).get('GH_TOKEN'), 'read-only')
            bc.api(f'repos/{REPO}/pulls/7/merge', method='PUT', payload={'sha': B})
            self.assertEqual(execute.call_args.kwargs.get('env', {}).get('GH_TOKEN', 'merge-bot'), 'merge-bot')
            bc.final_gate(REPO, 7, require_checks=True)
            self.assertEqual(execute.call_args.kwargs.get('env', {}).get('GH_TOKEN'), 'read-only')

    def test_pause_requires_timezone_and_bounded_future(self):
        now = dt.datetime(2026, 10, 31, tzinfo=dt.UTC)
        bc.validate_pause('2026-10-31T01:00:00Z', now)
        for value in ('2026-10-31T00:00:00Z', '2026-10-31T03:00:00Z', '2026-10-31T01:00:00'):
            with self.assertRaises(ValueError):
                bc.validate_pause(value, now)

    def test_canonical_repository_cannot_be_caller_selected(self):
        with patch.dict('os.environ', {'GITHUB_REPOSITORY': REPO}):
            self.assertEqual(bc.canonical_repository(REPO), REPO)
            with self.assertRaises(ValueError):
                bc.canonical_repository('other/repo')

    def test_gate_advisory_excludes_checks_merge_requires_them(self):
        result = type('Result', (), {'returncode': 0, 'stdout': '{"status":"PASSED","gate_scope":"final","exit_code":0}'})()
        with patch.object(bc.shared, 'command', return_value=result) as command:
            bc.final_gate(REPO, 7, require_checks=False)
            self.assertNotIn('--require-checks', command.call_args.args[0])
            bc.final_gate(REPO, 7, require_checks=True)
            self.assertIn('--require-checks', command.call_args.args[0])


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', {'GITHUB_REPOSITORY': REPO, 'GH_TOKEN': 'secret',
                                            'GH_TRUNK_MERGE_CREDENTIAL': 'event-capable', 'GITHUB_REF': 'refs/heads/main',
                                            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_ACTOR': 'admin',
                                            'GH_TRUNK_MERGE_DEADLINE_EPOCH': str(__import__('time').time() + 480)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.pr = pull()
        self.calls = []

    def api(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        if endpoint.endswith('/permission'):
            return {'permission': 'maintain'}
        if endpoint.endswith('/pulls/7/merge'):
            self.pr.update(merged=True, state='closed', merge_commit_sha=C)
            return {'merged': True, 'sha': C}
        if endpoint.endswith('/pulls/7'):
            return copy.deepcopy(self.pr)
        if endpoint.endswith('/git/ref/heads/main'):
            return {'object': {'sha': C if self.pr['merged'] else A}}
        if endpoint.endswith('/git/ref/heads/develop'):
            return {'object': {'sha': B}}
        if endpoint.endswith('/git/commits/' + C):
            return {'parents': [{'sha': A}, {'sha': B}]}
        if '/compare/' in endpoint:
            return {'status': 'ahead', 'merge_base_commit': {'sha': endpoint.split('/compare/')[1].split('...')[0]}}
        raise AssertionError(endpoint)

    def invoke(self, directory):
        return bc.main(['merge', '--repo', REPO, '--pr', '7', '--expected-head', B,
                        '--expected-base', A, '--approval', 'confirm-release', '--actor', 'admin',
                        '--writers-pause-until-utc', (dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat(),
                        '--output-dir', directory])

    def test_merge_uses_exact_head_clean_message_and_verifies_parents(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(bc, 'api', side_effect=self.api), \
                patch.object(bc, 'collect_readiness', return_value={'status': 'ready', 'direction': 'release'}), \
                patch.object(bc, 'final_gate', return_value={'passed': True}):
            self.assertEqual(self.invoke(directory), 0)
            request = next(row[1]['payload'] for row in self.calls if row[0].endswith('/merge'))
            self.assertEqual(request['sha'], B)
            self.assertEqual(request['merge_method'], 'merge')
            self.assertNotIn('[skip ci]', request['commit_title'])
            self.assertEqual(json.loads((Path(directory) / 'merge.json').read_text())['status'], 'merged')

    def test_stale_base_never_sends_merge(self):
        self.pr['base']['sha'] = C
        with tempfile.TemporaryDirectory() as directory, patch.object(bc, 'api', side_effect=self.api):
            self.assertEqual(self.invoke(directory), 2)
            self.assertFalse(any(row[0].endswith('/merge') for row in self.calls))


class ProvenanceTests(unittest.TestCase):
    def test_snapshot_requires_current_main_single_parent_same_tree_and_exact_message(self):
        pr = pull()
        pr['head']['ref'], pr['base']['ref'] = f'sync/main-to-develop/{A}', 'develop'
        source = {'tree': {'sha': C}}
        snapshot = {'tree': {'sha': C}, 'parents': [{'sha': A}],
                    'message': f'chore(repo): validate main {A} sync'}
        with patch.object(bc, 'ref', return_value=A), patch.object(bc, 'api', side_effect=[snapshot, source]):
            self.assertEqual(bc.direction(pr, REPO), 'sync')
            bc.validate_snapshot(REPO, pr)
        for change in ({'message': snapshot['message'] + ' [skip ci]'}, {'parents': [{'sha': B}]},
                       {'tree': {'sha': B}}):
            with patch.object(bc, 'ref', return_value=A), \
                    patch.object(bc, 'api', side_effect=[{**snapshot, **change}, source]), \
                    self.assertRaises(bc.PolicyBlock):
                bc.validate_snapshot(REPO, pr)

    def test_ci_receipt_download_requires_actual_jobs_and_matching_attempt(self):
        run = {'id': 10, 'run_attempt': 2, 'head_sha': B, 'html_url': 'https://github.com/owner/project/actions/runs/10'}
        receipt = {'schema_version': 'branch-validation.v1', 'repository': REPO, 'pr_number': 7,
                   'head_sha': B, 'base_sha': A, 'tested_merge_sha': C,
                   'run_id': 10, 'run_attempt': 2, 'merge_parents': [A, B]}
        jobs = [{'name': name, 'conclusion': 'success', 'html_url': run['html_url']} for name in bc.REQUIRED_JOBS]
        artifacts = [{'name': 'branch-validation-10-2', 'expired': False, 'size_in_bytes': 500}]

        def download(argv, **kwargs):
            (Path(argv[-1]) / 'context.json').write_text(json.dumps(receipt))

        with patch.object(bc, 'rows', side_effect=[jobs, artifacts]), \
                patch.object(bc.shared, 'command', side_effect=download), \
                patch.object(bc, 'api', return_value={'parents': [{'sha': A}, {'sha': B}]}):
            self.assertEqual(bc.validation_receipt(REPO, pull(), run)['tested_merge_sha'], C)
        jobs[0]['conclusion'] = 'skipped'
        with patch.object(bc, 'rows', return_value=jobs), self.assertRaises(bc.PolicyBlock):
            bc.validation_receipt(REPO, pull(), run)

    def test_metadata_only_run_never_supplies_source_validation(self):
        run = {'id': 10, 'run_number': 10, 'run_attempt': 1, 'head_sha': B,
               'path': '.github/workflows/ci.yml', 'head_repository': {'full_name': REPO},
               'event': 'pull_request_target', 'status': 'completed', 'conclusion': 'success'}
        with patch.object(bc, 'rows', return_value=[run]), self.assertRaises(bc.PolicyBlock):
            bc.source_validation(REPO, pull())

    def test_event_without_pull_links_locates_only_current_supported_pr(self):
        event = {'repository': {'full_name': REPO}, 'action': 'completed', 'workflow_run': {
            'id': 10, 'name': 'Checks / Python', 'path': '.github/workflows/ci.yml', 'head_sha': B,
            'head_branch': 'develop', 'head_repository': {'full_name': REPO}, 'pull_requests': []}}
        wrong = pull()
        wrong['head']['sha'] = A
        response = type('Result', (), {'stdout': json.dumps([pull(), wrong])})()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'event.json'
            path.write_text(json.dumps(event))
            with patch.object(bc.shared, 'command', return_value=response), \
                    patch.object(bc, 'api', return_value=event['workflow_run']):
                self.assertEqual(bc.event_prs(REPO, 'workflow_run', str(path)), [7])
            event['workflow_run']['path'] = '.github/workflows/evil.yml'
            path.write_text(json.dumps(event))
            with patch.object(bc, 'api', return_value=event['workflow_run']):
                self.assertEqual(bc.event_prs(REPO, 'workflow_run', str(path)), [])


class RecoveryTests(MergeTests):
    def test_timeout_reconciles_success_without_second_put(self):
        import subprocess

        def timeout_after_write(endpoint, **kwargs):
            result = self.api(endpoint, **kwargs)
            if endpoint.endswith('/merge'):
                raise subprocess.TimeoutExpired('gh', 60)
            return result

        with tempfile.TemporaryDirectory() as directory, patch.object(bc, 'api', side_effect=timeout_after_write), \
                patch.object(bc, 'collect_readiness', return_value={'status': 'ready'}), \
                patch.object(bc, 'final_gate', return_value={'passed': True}):
            self.assertEqual(self.invoke(directory), 0)
            self.assertEqual(sum(endpoint.endswith('/merge') for endpoint, _ in self.calls), 1)

    def test_completed_merge_with_wrong_parents_is_explicit_anomaly(self):
        def wrong_parent(endpoint, **kwargs):
            result = self.api(endpoint, **kwargs)
            return {'parents': [{'sha': A}, {'sha': A}]} if endpoint.endswith('/git/commits/' + C) else result

        with tempfile.TemporaryDirectory() as directory, patch.object(bc, 'api', side_effect=wrong_parent), \
                patch.object(bc, 'collect_readiness', return_value={'status': 'ready'}), \
                patch.object(bc, 'final_gate', return_value={'passed': True}):
            self.assertEqual(self.invoke(directory), 1)
            result = json.loads((Path(directory) / 'merge.json').read_text())
            self.assertIn('ANOMALY', result['reason'])
            self.assertEqual(sum(endpoint.endswith('/merge') for endpoint, _ in self.calls), 1)

    def test_idempotence_verifies_evidence_without_mutation(self):
        self.pr.update(merged=True, state='closed', merge_commit_sha=C)
        with tempfile.TemporaryDirectory() as directory, patch.object(bc, 'api', side_effect=self.api):
            self.assertEqual(self.invoke(directory), 0)
            self.assertFalse(any(endpoint.endswith('/merge') for endpoint, _ in self.calls))

    def test_base_change_during_gate_blocks_write(self):
        def gate(*args, **kwargs):
            self.pr['base']['sha'] = C
            return {'passed': True}

        with tempfile.TemporaryDirectory() as directory, patch.object(bc, 'api', side_effect=self.api), \
                patch.object(bc, 'collect_readiness', return_value={'status': 'ready'}), \
                patch.object(bc, 'final_gate', side_effect=gate):
            self.assertEqual(self.invoke(directory), 2)
            self.assertFalse(any(endpoint.endswith('/merge') for endpoint, _ in self.calls))


class CredentialTests(unittest.TestCase):
    def test_runtime_credentials_are_narrowly_opted_in(self):
        import sys

        with self.assertRaises(ValueError):
            bc.shared.command([sys.executable, '-c', 'print(1)'], trusted_runtime=True)
        with patch.dict('os.environ', {'GH_TOKEN': 'secret', 'GH_TRUNK_READ_TOKEN': 'read-secret'}):
            result = bc.shared.command([sys.executable, '-c',
                                       'import os; print(os.environ.get("GH_TOKEN", "absent"), os.environ.get("GH_TRUNK_READ_TOKEN", "absent"))'])
            self.assertEqual(result.stdout.strip(), 'absent absent')


class ReleaseHistoryTests(unittest.TestCase):
    def test_real_git_history_uses_reachable_stable_baseline_and_commit_messages(self):
        original = bc.shared.command
        captured = {}

        def command(argv, **kwargs):
            if argv[0] == bc.GH:
                return type('Result', (), {'stdout': '[]'})()
            if argv[0] == 'node':
                captured.update(json.loads(Path(argv[-1]).read_text()))
                self.assertNotIn('secret', argv[3])
                return type('Result', (), {'stdout': '{"release_type":"minor"}', 'returncode': 0})()
            return original(argv, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original([bc.GIT, 'init', '--quiet', directory])
            original([bc.GIT, '-C', directory, 'config', 'user.name', 'Test'])
            original([bc.GIT, '-C', directory, 'config', 'user.email', 'test@example.invalid'])
            (root / 'source').write_text('baseline')
            (root / 'pyproject.toml').write_text('[project]\nversion = "1.2.4"\n')
            original([bc.GIT, '-C', directory, 'add', 'source'])
            original([bc.GIT, '-C', directory, 'commit', '--quiet', '-m', 'chore: initial'])
            original([bc.GIT, '-C', directory, 'tag', 'v1.2.3'])
            original([bc.GIT, '-C', directory, 'commit', '--quiet', '--allow-empty', '-m', 'feat: real capability'])
            head = original([bc.GIT, '-C', directory, 'rev-parse', 'HEAD']).stdout.strip()
            pr = pull()
            pr['head']['sha'] = head
            pr['base']['sha'] = head
            pr['title'] = 'fix: misleading title'
            with patch.object(bc, 'ROOT', root), patch.object(bc.shared, 'command', side_effect=command):
                self.assertEqual(bc.release_analysis(REPO, pr)['release_type'], 'minor')
            self.assertEqual(captured['baseline_tag'], 'v1.2.3')
            self.assertEqual(captured['current_version'], '1.2.4')
            self.assertEqual(captured['commits'], [{'hash': head, 'message': 'feat: real capability\n'}])


class PublicationRoutingTests(unittest.TestCase):
    def test_release_run_without_pr_links_finds_completed_promotion(self):
        merged = pull()
        merged.update(merged=True, merged_at='2026-10-31T00:00:00Z', state='closed', merge_commit_sha=C)
        event = {'repository': {'full_name': REPO}, 'action': 'completed', 'workflow_run': {
            'id': 10, 'name': 'Release', 'path': '.github/workflows/release.yml', 'head_sha': C,
            'head_branch': 'main', 'head_repository': {'full_name': REPO}, 'pull_requests': []}}
        responses = [type('Result', (), {'stdout': '[]'})(),
                     type('Result', (), {'stdout': json.dumps([merged])})()]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'event.json'
            path.write_text(json.dumps(event))
            with patch.object(bc.shared, 'command', side_effect=responses), \
                    patch.object(bc, 'api', return_value=event['workflow_run']):
                self.assertEqual(bc.event_prs(REPO, 'workflow_run', str(path)), [7])


class RetainedHistoryTests(MergeTests):
    def test_deleted_snapshot_ref_does_not_invalidate_successful_sync(self):
        args = bc.parser().parse_args(['merge', '--repo', REPO, '--pr', '7', '--expected-head', B,
                                      '--expected-base', A, '--approval', 'confirm-sync', '--actor', 'admin',
                                      '--writers-pause-until-utc', '2026-10-31T01:00:00Z', '--output-dir', '/tmp'])
        pr = pull()
        pr['head']['ref'], pr['base']['ref'] = f'sync/main-to-develop/{A}', 'develop'
        pr.update(merged=True, merge_commit_sha=C)
        with patch.object(bc, 'ref', side_effect=lambda repo, name: {'main': A, 'develop': C}[name]), \
                patch.object(bc, 'api', side_effect=self.api):
            self.assertEqual(bc.verify_merged(REPO, pr, args)['status'], 'merged')

    def test_target_can_advance_when_merge_remains_ancestor(self):
        args = bc.parser().parse_args(['merge', '--repo', REPO, '--pr', '7', '--expected-head', B,
                                      '--expected-base', A, '--approval', 'confirm-release', '--actor', 'admin',
                                      '--writers-pause-until-utc', '2026-10-31T01:00:00Z', '--output-dir', '/tmp'])
        self.pr.update(merged=True, merge_commit_sha=C)
        with patch.object(bc, 'ref', side_effect=lambda repo, name: {'main': 'd' * 40, 'develop': B}[name]), \
                patch.object(bc, 'api', side_effect=self.api):
            self.assertEqual(bc.verify_merged(REPO, self.pr, args)['status'], 'merged')


class ProposalRoutingTests(unittest.TestCase):
    def test_schedule_only_selects_release_and_empty_dispatch_emits_summary(self):
        sync = pull()
        sync['number'] = 8
        sync['head']['ref'], sync['base']['ref'] = f'sync/main-to-develop/{A}', 'develop'
        response = type('Result', (), {'stdout': json.dumps([pull(), sync])})()
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict('os.environ', {'GITHUB_REF': 'refs/heads/main', 'GITHUB_REPOSITORY': REPO}):
            path = Path(directory) / 'event.json'
            path.write_text(json.dumps({'repository': {'full_name': REPO}}))
            with patch.object(bc.shared, 'command', return_value=response):
                self.assertEqual(bc.event_prs(REPO, 'schedule', str(path)), [7])
            path.write_text(json.dumps({'repository': {'full_name': REPO}, 'inputs': {'operation': 'propose-sync'}}))
            with patch.object(bc.shared, 'command', return_value=type('Result', (), {'stdout': '[]'})()):
                self.assertEqual(bc.main(['readiness', '--repo', REPO, '--event-name', 'workflow_dispatch',
                                          '--event-file', str(path), '--output-dir', directory]), 0)
            self.assertEqual(json.loads((Path(directory) / 'readiness.json').read_text())['status'], 'no-candidates')
            self.assertTrue((Path(directory) / 'readiness.md').is_file())


class DeadlineTests(unittest.TestCase):
    def test_shared_command_timeout_is_bounded_and_validated(self):
        import math
        import sys
        for timeout in (0, -1, math.inf, math.nan):
            with self.assertRaises(ValueError):
                bc.shared.command([sys.executable, '-c', 'pass'], timeout=timeout)
        with self.assertRaises(__import__('subprocess').TimeoutExpired):
            bc.shared.command([sys.executable, '-c', 'import time; time.sleep(2)'], timeout=0.02)

    def test_api_and_gate_pass_actual_timeout_and_reserve_deadline(self):
        result = type('Result', (), {'stdout': '{}', 'returncode': 0})()
        with patch.object(bc.shared, 'command', return_value=result) as command, \
                patch.dict('os.environ', {'GH_TRUNK_MERGE_DEADLINE_EPOCH': '1100'}), \
                patch.object(bc.time, 'time', return_value=1000):
            bc.api('repos/owner/project/pulls/7')
            self.assertEqual(command.call_args.kwargs['timeout'], 30)
            bc.api('repos/owner/project/pulls/7/merge', method='PUT', payload={'sha': B})
            self.assertEqual(command.call_args.kwargs['timeout'], 20)
            bc.final_gate(REPO, 7, require_checks=True)
            self.assertLessEqual(command.call_args.kwargs['timeout'], 70)
        with patch.dict('os.environ', {'GH_TRUNK_MERGE_DEADLINE_EPOCH': '1040'}), \
                patch.object(bc.time, 'time', return_value=1000), \
                patch.object(bc.shared, 'command') as command, self.assertRaises(bc.PolicyBlock):
            bc.api('repos/owner/project/pulls/7/merge', method='PUT', payload={'sha': B})
        command.assert_not_called()


class ReadinessProjectionTests(unittest.TestCase):
    def test_pending_ci_still_reports_review_and_current_release(self):
        with patch.object(bc, 'ref', side_effect=[A, B]), \
                patch.object(bc, 'source_validation', side_effect=bc.PolicyBlock('CI pending')), \
                patch.object(bc, 'final_gate', return_value={'passed': True, 'result': {}}), \
                patch.object(bc, 'release_analysis', return_value={'release_type': 'minor', 'current_version': '1.2.3'}), \
                patch.object(bc, 'publication', return_value=[]):
            result = bc.collect_readiness(REPO, pull())
            self.assertEqual(result['status'], 'blocked')
            self.assertTrue(result['review_gate']['passed'])
            markdown = bc.markdown_summary(result)
            for text in ('1.2.3', 'minor', 'Approval', 'CI', 'Review', 'cooperative'):
                self.assertIn(text, markdown)


class HumanReportTests(MergeTests):
    def test_success_and_unknown_have_human_reports_without_private_paths(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(bc, 'api', side_effect=self.api), \
                patch.object(bc, 'collect_readiness', return_value={'status': 'ready'}), \
                patch.object(bc, 'final_gate', return_value={'passed': True}):
            self.assertEqual(self.invoke(directory), 0)
            markdown = (Path(directory) / 'merge.md').read_text()
            self.assertIn(f'https://github.com/{REPO}/commit/{C}', markdown)
            self.assertIn('actions/workflows/release.yml', markdown)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(bc, 'api', side_effect=OSError('/private/local/secret-machine')):
            self.assertEqual(self.invoke(directory), 1)
            markdown = (Path(directory) / 'merge.md').read_text()
            self.assertNotIn('/private/local', markdown)
            self.assertIn('unknown', markdown)


class BoundedRecoveryTests(MergeTests):
    def test_real_timeout_in_merge_command_reconciles_once(self):
        import subprocess
        import sys
        original = bc.shared.command
        seen_timeouts = []

        def command(argv, **kwargs):
            endpoint = argv[argv.index('--method') + 2]
            if '--input' in argv:
                payload = json.loads(Path(argv[-1]).read_text())
                result = self.api(endpoint, method='PUT', payload=payload)
                seen_timeouts.append(kwargs['timeout'])
                original([sys.executable, '-c', 'import time; time.sleep(2)'], timeout=0.02)
                raise AssertionError(result)
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.api(endpoint)), '')

        with tempfile.TemporaryDirectory() as directory, patch.object(bc.shared, 'command', side_effect=command), \
                patch.object(bc, 'collect_readiness', return_value={'status': 'ready'}), \
                patch.object(bc, 'final_gate', return_value={'passed': True}):
            self.assertEqual(self.invoke(directory), 0)
            self.assertEqual(seen_timeouts, [20])
            self.assertEqual(sum(endpoint.endswith('/merge') for endpoint, _ in self.calls), 1)

    def test_maintain_role_is_accepted_and_plain_write_is_rejected(self):
        for permission, expected in (({'permission': 'write', 'role_name': 'maintain'}, 0),
                                     ({'permission': 'write'}, 2)):
            self.pr = pull()
            self.calls = []

            def api(endpoint, permission=permission, **kwargs):
                return permission if endpoint.endswith('/permission') else self.api(endpoint, **kwargs)

            with tempfile.TemporaryDirectory() as directory, patch.object(bc, 'api', side_effect=api), \
                    patch.object(bc, 'collect_readiness', return_value={'status': 'ready'}), \
                    patch.object(bc, 'final_gate', return_value={'passed': True}):
                self.assertEqual(self.invoke(directory), expected)
                if expected:
                    self.assertFalse(any(endpoint.endswith('/merge') for endpoint, _ in self.calls))


class PublicationEvidenceTests(unittest.TestCase):
    def test_successful_dry_run_is_not_published(self):
        jobs = [{'name': 'build-release-package', 'status': 'completed', 'conclusion': 'success'},
                {'name': 'publish-pypi', 'status': 'completed', 'conclusion': 'skipped'},
                {'name': 'publish-homebrew', 'status': 'completed', 'conclusion': 'skipped'}]
        result = bc.publication_evidence(jobs)
        self.assertEqual(result['status'], 'publication not verified')
        self.assertEqual(result['pypi'], 'not-published')
        self.assertEqual(set(result['bottle_targets'].values()), {'not-started'})

    def test_all_production_jobs_are_required_for_publication_observation(self):
        jobs = [{'name': 'publish-pypi', 'status': 'completed', 'conclusion': 'success'},
                {'name': 'publish-homebrew / publish-tap', 'status': 'completed', 'conclusion': 'success'}]
        jobs.extend({'name': f'publish-homebrew / verify-bottles ({runner})', 'status': 'completed',
                     'conclusion': 'success'} for runner in bc.shared.TARGETS)
        self.assertEqual(bc.publication_evidence(jobs)['status'], 'production publication observed')
        jobs.pop()
        self.assertEqual(bc.publication_evidence(jobs)['status'], 'publication not verified')
