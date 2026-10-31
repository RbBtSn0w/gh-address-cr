"""Read-only readiness projection and explicitly authorized trunk merge boundary.

GitHub owns repository facts; the installed runtime owns review truth. These
reports never become a persistence boundary or authorize later invocations.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from urllib.parse import quote

from gh_address_cr.otel_tracing import add_current_span_event
from scripts.release import homebrew_support as shared

START = '<!-- gh-address-cr:branch-readiness:start -->'
END = '<!-- gh-address-cr:branch-readiness:end -->'
SHA = re.compile(r'[a-f0-9]{40}')
REPO = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
REQUIRED_JOBS = {'lint-and-test (3.12)', 'lint-and-test (3.13)', 'lint-and-test (3.14)',
                 'otel-minimum-versions', 'Validate base branch', 'Record PR validation context'}
ROOT = Path(__file__).resolve().parents[2]
GH = '/opt/homebrew/bin/gh' if Path('/opt/homebrew/bin/gh').is_file() else 'gh'
GIT = '/opt/homebrew/bin/git' if Path('/opt/homebrew/bin/git').is_file() else 'git'


class PolicyBlock(ValueError):
    """Known unsafe or stale authorization; no write is permitted."""


def bounded_json(text: str) -> dict:
    if len(text.encode()) > 4_000_000:
        raise ValueError('GitHub payload exceeds bounded input size')
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    return value


def deadline_remaining(*, required: bool = False) -> float | None:
    value = os.environ.get('GH_TRUNK_MERGE_DEADLINE_EPOCH')
    if value is None:
        if required:
            raise PolicyBlock('Guarded merge execution deadline is required')
        return None
    try:
        remaining = float(value) - time.time()
    except ValueError as exc:
        raise PolicyBlock('Invalid guarded merge execution deadline') from exc
    if not math.isfinite(remaining) or remaining <= 30:
        raise PolicyBlock('Execution deadline reached; report reserve retained')
    return remaining


def branch_command(argv: list[str], *, timeout: float = 30, **kwargs) -> subprocess.CompletedProcess[str]:
    remaining = deadline_remaining()
    if remaining is not None:
        timeout = min(timeout, remaining - 30)
    # Installation merge credentials need no Actions permission. Read evidence
    # with the job's read-only token, while mutation requests retain the Bot.
    read_token = os.environ.get('GH_TRUNK_READ_TOKEN')
    is_read = argv[:3] == [GH, 'run', 'download']
    if argv[:2] == [GH, 'api']:
        is_read = (argv[argv.index('--method') + 1] == 'GET' if '--method' in argv
                   else not any(flag in argv for flag in ('--input', '-f', '-F', '--field', '--raw-field')))
    if read_token and (is_read or kwargs.get('trusted_runtime')):
        kwargs['env'] = {**os.environ, **kwargs.get('env', {}), 'GH_TOKEN': read_token}
    return shared.command(argv, timeout=timeout, **kwargs)


def api(endpoint: str, *, payload: dict | None = None, method: str = 'GET') -> dict:
    timeout = 20 if method == 'PUT' else 30
    remaining = deadline_remaining()
    if method == 'PUT' and (remaining is None or remaining < 60):
        raise PolicyBlock('Insufficient execution budget for merge and reconciliation')
    argv = [GH, 'api', '--hostname', 'github.com', '--method', method, endpoint]
    if payload is not None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'request.json'
            shared.write_json(path, payload)
            return bounded_json(branch_command([*argv, '--input', str(path)], timeout=timeout).stdout)
    return bounded_json(branch_command(argv, timeout=timeout).stdout)


def rows(endpoint: str, key: str) -> list[dict]:
    result = api(endpoint + ('&' if '?' in endpoint else '?') + 'per_page=100')[key]
    if not isinstance(result, list) or len(result) >= 100:
        raise ValueError('Ambiguous or truncated GitHub collection')
    return result


def canonical_repository(requested: str) -> str:
    canonical = os.environ.get('GITHUB_REPOSITORY', '')
    if not canonical:
        remote = branch_command([GIT, 'remote', 'get-url', 'origin'], cwd=ROOT).stdout.strip()
        match = re.fullmatch(r'(?:https://github.com/|git@github.com:)([^/]+/[^/]+?)(?:\.git)?', remote)
        canonical = match[1] if match else ''
    if not REPO.fullmatch(canonical) or requested != canonical:
        raise ValueError('Repository differs from trusted execution repository')
    return canonical


def direction(pr: dict, repo: str) -> str:
    head, base = pr['head'], pr['base']
    if any(side.get('repo', {}).get('full_name') != repo for side in (head, base)):
        raise ValueError('Cross-repository pull requests are unsupported')
    if not all(SHA.fullmatch(side.get('sha', '')) for side in (head, base)):
        raise ValueError('Invalid pull request commit identity')
    if (head['ref'], base['ref']) == ('develop', 'main'):
        return 'release'
    if base['ref'] == 'develop' and re.fullmatch(r'sync/main-to-develop/[a-f0-9]{40}', head['ref']):
        return 'sync'
    raise ValueError('Unsupported trunk direction')


def ref(repo: str, name: str) -> str:
    return api(f'repos/{repo}/git/ref/heads/{quote(name, safe="/")}')['object']['sha']


def validate_snapshot(repo: str, pr: dict) -> None:
    main = ref(repo, 'main')
    if pr['head']['ref'] != f'sync/main-to-develop/{main}':
        raise PolicyBlock('Sync snapshot is not from current main')
    commit = api(f'repos/{repo}/git/commits/{pr["head"]["sha"]}')
    source = api(f'repos/{repo}/git/commits/{main}')
    if ([row['sha'] for row in commit['parents']] != [main]
            or commit['tree']['sha'] != source['tree']['sha']
            or commit['message'] != f'chore(repo): validate main {main} sync'):
        raise PolicyBlock('Sync snapshot provenance is invalid')


def final_gate(repo: str, number: int, *, require_checks: bool) -> dict:
    argv = [sys.executable, '-m', 'gh_address_cr', 'final-gate', repo, str(number), '--machine']
    if require_checks:
        argv.append('--require-checks')
    result = branch_command(argv, cwd=ROOT, check=False, trusted_runtime=True, timeout=180)
    output = bounded_json(result.stdout)
    passed = (result.returncode == 0 and output.get('exit_code') == 0
              and output.get('status') == 'PASSED' and output.get('gate_scope') == 'final')
    # Only review facts belong in this public projection. Runtime artifact paths,
    # invocation telemetry and completion prose stay in their owning reports.
    observed = {key: output[key] for key in ('status', 'reason_code', 'failure_codes', 'counts') if key in output}
    return {'passed': passed, 'result': observed}


def validate_receipt(receipt: dict, run: dict, pr: dict, repo: str, commit: dict) -> None:
    expected = {'schema_version': 'branch-validation.v1', 'repository': repo, 'pr_number': pr['number'],
                'head_sha': pr['head']['sha'], 'base_sha': pr['base']['sha'],
                'run_id': run['id'], 'run_attempt': run['run_attempt'],
                'merge_parents': [pr['base']['sha'], pr['head']['sha']]}
    if (any(receipt.get(key) != value for key, value in expected.items())
            or not SHA.fullmatch(receipt.get('tested_merge_sha', ''))
            or [row['sha'] for row in commit.get('parents', [])] != expected['merge_parents']
            or run['head_sha'] != pr['head']['sha']):
        raise PolicyBlock('CI validation context does not bind current base/head and tested merge')


def validation_receipt(repo: str, pr: dict, run: dict) -> dict:
    jobs = rows(f'repos/{repo}/actions/runs/{run["id"]}/attempts/{run["run_attempt"]}/jobs', 'jobs')
    actual = {row['name']: row for row in jobs}
    if not REQUIRED_JOBS <= actual.keys() or any(actual[name]['conclusion'] != 'success' for name in REQUIRED_JOBS):
        raise PolicyBlock('Required actual CI jobs are missing or unsuccessful')
    artifacts = rows(f'repos/{repo}/actions/runs/{run["id"]}/artifacts', 'artifacts')
    name = f'branch-validation-{run["id"]}-{run["run_attempt"]}'
    matching = [item for item in artifacts if item['name'] == name and not item.get('expired')]
    if len(matching) != 1 or matching[0].get('size_in_bytes', 0) > 65536:
        raise PolicyBlock('CI validation artifact missing, ambiguous, expired or too large')
    with tempfile.TemporaryDirectory() as directory:
        branch_command([GH, 'run', 'download', str(run['id']), '--repo', repo, '--name', name, '--dir', directory])
        files = list(Path(directory).rglob('*'))
        if len(files) != 1 or files[0].name != 'context.json' or not files[0].is_file() or files[0].is_symlink():
            raise ValueError('Validation artifact must contain only context.json')
        if files[0].stat().st_size > 65536:
            raise ValueError('Validation receipt too large')
        receipt = bounded_json(files[0].read_text())
    merge_sha = receipt.get('tested_merge_sha', '')
    if not SHA.fullmatch(merge_sha):
        raise ValueError('Invalid tested merge SHA')
    commit = api(f'repos/{repo}/git/commits/{merge_sha}')
    validate_receipt(receipt, run, pr, repo, commit)
    return {'run_id': run['id'], 'run_attempt': run['run_attempt'], 'tested_merge_sha': merge_sha,
            'url': run['html_url'], 'jobs': [{'name': job['name'], 'conclusion': job['conclusion'],
                                              'url': job['html_url']} for job in jobs]}


def source_validation(repo: str, pr: dict) -> dict:
    runs = rows(f'repos/{repo}/actions/workflows/ci.yml/runs?head_sha={pr["head"]["sha"]}&event=pull_request',
                'workflow_runs')
    candidates = [run for run in runs if run.get('path') == '.github/workflows/ci.yml'
                  and run.get('head_repository', {}).get('full_name') == repo
                  and run.get('head_sha') == pr['head']['sha'] and run.get('event') == 'pull_request']
    if not candidates:
        raise PolicyBlock('No source CI run for current head')
    run = max(candidates, key=lambda item: (item['run_number'], item['run_attempt']))
    if run.get('status') != 'completed' or run.get('conclusion') != 'success':
        raise PolicyBlock('Latest source CI run is not successful')
    return validation_receipt(repo, pr, run)


def release_analysis(repo: str, pr: dict) -> dict:
    # Changed policy is reviewed separately; never execute candidate configuration.
    response = branch_command([GH, 'api', '--hostname', 'github.com',
                               f'repos/{repo}/pulls/{pr["number"]}/files?per_page=100']).stdout
    if len(response.encode()) > 4_000_000:
        raise ValueError('Changed file payload too large')
    files = json.loads(response)
    if not isinstance(files, list) or len(files) >= 100:
        raise PolicyBlock('Changed file set is truncated')
    if any(item['filename'] in {'release.config.cjs', 'package.json'} for item in files):
        return {'release_type': 'unknown', 'reason': 'Candidate changes release analyzer policy'}
    tags = branch_command([GIT, 'for-each-ref', '--merged', pr['base']['sha'],
                           '--sort=-version:refname', '--format=%(refname:short)', 'refs/tags'], cwd=ROOT).stdout
    stable = [tag for tag in tags.splitlines() if re.fullmatch(r'v\d+\.\d+\.\d+', tag)]
    if not stable:
        return {'release_type': 'unknown', 'reason': 'No reachable stable release baseline'}
    baseline = stable[0]
    current_version = trusted_current_version()
    history = branch_command([GIT, 'log', '-z', '--format=%H%x00%B',
                              f'{baseline}..{pr["head"]["sha"]}'], cwd=ROOT).stdout
    if len(history.encode()) > 4_000_000:
        raise ValueError('Release commit history exceeds bounded input size')
    tokens = history.rstrip('\x00').split('\x00') if history else []
    if len(tokens) % 2:
        raise ValueError('Malformed git commit history')
    commits = [{'hash': tokens[index], 'message': tokens[index + 1]} for index in range(0, len(tokens), 2)]
    # Stock Node is an external operation, not another authored CLI. The static
    # wrapper imports only this trusted checkout's library and reads JSON data.
    wrapper = ("import fs from 'node:fs'; import {analyzeRelease} from './scripts/release/analyze_branch_release.mjs'; "
               "const input=JSON.parse(fs.readFileSync(process.argv[1],'utf8')); "
               "console.log(JSON.stringify(await analyzeRelease(input)));")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'commits.json'
        shared.write_json(path, {'commits': commits, 'current_version': current_version, 'baseline_tag': baseline})
        result = branch_command(['node', '--input-type=module', '--eval', wrapper, str(path)], cwd=ROOT, check=False)
    if result.returncode:
        return {'release_type': 'unknown', 'reason': 'Trusted release analyzer unavailable'}
    data = bounded_json(result.stdout)
    if data.get('release_type') not in {'major', 'minor', 'patch', None}:
        raise ValueError('Unsupported release analyzer output')
    return data


def trusted_current_version() -> str:
    with (ROOT / 'pyproject.toml').open('rb') as handle:
        return tomllib.load(handle)['project']['version']


def observed_job(jobs: list[dict], name: str) -> str:
    matches = [job for job in jobs if job['name'].rsplit(' / ', 1)[-1] == name]
    if not matches:
        return 'not-started'
    if len(matches) != 1:
        return 'ambiguous'
    job = matches[0]
    if job.get('conclusion') == 'skipped':
        return 'not-published'
    return job.get('conclusion') or job.get('status', 'unknown')


def publication_evidence(jobs: list[dict]) -> dict:
    pypi = observed_job(jobs, 'publish-pypi')
    targets = {runner: observed_job(jobs, f'verify-bottles ({runner})') for runner in shared.TARGETS}
    tap = observed_job(jobs, 'publish-tap')
    bottles_verified = all(status == 'success' for status in targets.values()) and tap == 'success'
    published = pypi == 'success' and bottles_verified
    dry_run = (observed_job(jobs, 'build-release-package') == 'success' and pypi == 'not-published'
               and not bottles_verified)
    return {'status': 'production publication observed' if published else 'publication not verified',
            'mode': 'validation-only / not-published' if dry_run else 'job observations',
            'pypi': pypi, 'bottle_targets': targets, 'publish_tap': tap,
            'bottles_verified': bottles_verified}


def publication(repo: str, sha: str) -> list[dict]:
    result = []
    for workflow in ('release.yml', 'homebrew.yml'):
        for run in rows(f'repos/{repo}/actions/workflows/{workflow}/runs?head_sha={sha}', 'workflow_runs'):
            jobs = rows(f'repos/{repo}/actions/runs/{run["id"]}/jobs', 'jobs')
            result.append({'workflow': workflow, 'status': run['status'], 'conclusion': run['conclusion'],
                           'url': run['html_url'], 'publication_observation': publication_evidence(jobs),
                           'jobs': [{'name': job['name'], 'status': job['status'],
                           'conclusion': job['conclusion'], 'url': job['html_url']} for job in jobs]})
    return result


def collect_readiness(repo: str, pr: dict) -> dict:
    kind = direction(pr, repo)
    result = {'schema_version': 'branch-readiness.v1', 'repository': repo, 'pr_number': pr['number'],
              'direction': kind, 'head_sha': pr['head']['sha'], 'base_sha': pr['base']['sha'], 'blockers': []}
    if pr.get('merged'):
        if kind == 'release':
            result['release'] = {'release_type': None, 'current_version': trusted_current_version()}
        return {**result, 'status': 'merged', 'publication': publication(repo, pr['merge_commit_sha'])}
    try:
        if pr.get('state') != 'open' or pr.get('draft'):
            raise PolicyBlock('Pull request is closed or draft')
        if ref(repo, pr['base']['ref']) != pr['base']['sha'] or ref(repo, pr['head']['ref']) != pr['head']['sha']:
            raise PolicyBlock('Pull request refs are stale')
        if kind == 'sync':
            validate_snapshot(repo, pr)
    except PolicyBlock as exc:
        result['blockers'].append(str(exc))
        result['identity_validated'] = False
    else:
        result['identity_validated'] = True
        try:
            result['ci'] = source_validation(repo, pr)
        except PolicyBlock as exc:
            result['blockers'].append(str(exc))
        result['review_gate'] = final_gate(repo, pr['number'], require_checks=False)
        if not result['review_gate']['passed']:
            result['blockers'].append('Review final-gate is not passed')
        if kind == 'release':
            result['release'] = release_analysis(repo, pr)
            if result['release']['release_type'] == 'unknown':
                result['blockers'].append('Release type is unknown')
    result['publication'] = publication(repo, pr['head']['sha'])
    result['status'] = 'blocked' if result['blockers'] else 'ready'
    add_current_span_event('branch.readiness.completed', {'branch.direction': kind, 'branch.status': result['status']})
    return result


def replace_summary(body: str, markdown: str) -> str:
    if START in markdown or END in markdown:
        raise ValueError('Summary content contains ownership markers')
    if (body.count(START), body.count(END)) not in {(0, 0), (1, 1)}:
        raise ValueError('Malformed or duplicate readiness ownership markers')
    block = f'{START}\n{markdown.rstrip()}\n{END}'
    if START not in body:
        return body + ('\n\n' if body else '') + block
    start, end = body.index(START), body.index(END)
    if end < start or START in markdown or END in markdown:
        raise ValueError('Malformed readiness marker order')
    return body[:start] + block + body[end + len(END):]


def publication_markdown(data: dict) -> list[str]:
    lines = []
    observations = [run.get('publication_observation', publication_evidence(run['jobs']))
                    for run in data.get('publication', [])]
    verified = (any(row['pypi'] == 'success' for row in observations)
                and any(row['bottles_verified'] for row in observations))
    lines.extend(['', '**Publication:** ' + ('production publication observed' if verified else 'publication not verified'),
                  'Publication is advisory; pending bottles do not block promotion.'])
    if not observations:
        lines.extend(f'- Bottle target {runner}: not-started' for runner in shared.TARGETS)
    for run in data.get('publication', []):
        observation = run.get('publication_observation', publication_evidence(run['jobs']))
        lines.append(f'- [{run["workflow"]}]({run["url"]}): workflow {run["conclusion"] or run["status"]}; {observation["mode"]}')
        lines.append(f'  - Production PyPI: {observation["pypi"]}; tap: {observation["publish_tap"]}')
        lines.extend(f'  - Bottle target {runner}: {status}' for runner, status in observation['bottle_targets'].items())
        for job in run['jobs']:
            lines.append(f'  - [{job["name"]}]({job["url"]}): {job["conclusion"] or job["status"]}')
    return lines


def markdown_summary(data: dict) -> str:
    lines = ['### Trunk readiness', '', f'**Status:** {data["status"]}',
             f'**Direction:** {data["direction"]}', f'**Head:** `{data["head_sha"]}`',
             f'**Base:** `{data["base_sha"]}`']
    if data['status'] == 'merged':
        lines.extend(['', '**Merge:** already merged; no further merge approval is needed.'])
        if 'release' in data:
            lines.append(f'**Current version:** {data["release"].get("current_version", "unknown")}')
        lines.extend(['', '**Remaining actions:**',
                      '- Verify post-merge CI, production outcomes and reviewed sync-back.',
                      '- Resume coordinated writers only after the required verification.'])
        lines.extend(publication_markdown(data))
        return '\n'.join(lines) + '\n'
    lines.extend(['**Approval:** explicit admin/maintain dispatch with exact head/base is required.',
                  '**Writer pause:** cooperative; GitHub has no atomic expected-base lock.'])
    if 'release' in data:
        lines.append(f'**Current version:** {data["release"].get("current_version", "unknown")}')
        lines.append(f'**Release type:** {data["release"]["release_type"] or "none"}')
    ci = data.get('ci', {})
    jobs = ci.get('jobs', [])
    passed_jobs = sum(job.get('conclusion') == 'success' for job in jobs if job.get('name') in REQUIRED_JOBS)
    lines.append(f'**CI jobs:** {passed_jobs}/{len(REQUIRED_JOBS)} required jobs proven successful.')
    review = data.get('review_gate', {})
    lines.append(f'**Review gate:** {"passed" if review.get("passed") else "blocked or unavailable"}.')
    counts = review.get('result', {}).get('counts', {})
    lines.append(f'**Review items:** {counts.get("unresolved_remote_threads_count", "unknown")} unresolved threads; '
                 f'{counts.get("pending_current_login_review_count", "unknown")} pending reviews.')
    lines.extend(['', '**Remaining actions:**'])
    if data.get('blockers'):
        lines.extend(f'- Resolve: {reason}' for reason in data['blockers'])
    lines.extend(['- Refresh exact head/base and confirm writer pause before approval.',
                  '- Dispatch guarded merge; never merge from this advisory report.'])
    if 'ci' in data:
        lines.extend(['', f'[Source CI]({data["ci"]["url"]})'])
    lines.extend(publication_markdown(data))
    return '\n'.join(lines) + '\n'


def validate_pause(value: str, now: dt.datetime | None = None) -> None:
    instant = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    now = now or dt.datetime.now(dt.UTC)
    if instant.tzinfo is None or instant.utcoffset() != dt.timedelta(0) or not dt.timedelta(0) < instant - now <= dt.timedelta(hours=2):
        raise PolicyBlock('Writer pause must be a future UTC instant within two hours')


def validate_authorization(args: argparse.Namespace, repo: str) -> None:
    if (not os.environ.get('GH_TOKEN') or os.environ.get('GH_TRUNK_MERGE_CREDENTIAL') != 'event-capable'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or args.actor != os.environ.get('GITHUB_ACTOR')):
        raise PolicyBlock('Explicit dispatch with an event-capable credential from trusted main is required')
    if not re.fullmatch(r'[A-Za-z0-9-]{1,39}(?:\[bot\])?', args.actor):
        raise PolicyBlock('Invalid dispatch actor')
    permission = api(f'repos/{repo}/collaborators/{args.actor}/permission')
    if permission.get('role_name', permission.get('permission')) not in {'admin', 'maintain'}:
        raise PolicyBlock('Dispatch actor needs live admin or maintain permission')
    validate_pause(args.writers_pause_until_utc)
    remaining = deadline_remaining(required=True)
    if remaining is not None and remaining > 480:
        raise PolicyBlock('Execution deadline exceeds the guarded eight-minute budget')
    if not all(SHA.fullmatch(value) for value in (args.expected_head, args.expected_base)):
        raise PolicyBlock('Expected head and base must be full commit SHAs')


def exact_refs(repo: str, pr: dict, args: argparse.Namespace) -> None:
    if (pr['head']['sha'] != args.expected_head or pr['base']['sha'] != args.expected_base
            or ref(repo, pr['head']['ref']) != args.expected_head
            or ref(repo, pr['base']['ref']) != args.expected_base):
        raise PolicyBlock('Expected base/head authorization is stale')


def verify_merged(repo: str, pr: dict, args: argparse.Namespace) -> dict:
    merge = pr.get('merge_commit_sha', '')
    if not pr.get('merged') or not SHA.fullmatch(merge):
        raise ValueError('Merge acceptance is unknown; do not retry blindly')
    commit = api(f'repos/{repo}/git/commits/{merge}')
    parents = [item['sha'] for item in commit['parents']]
    if parents != [args.expected_base, args.expected_head] or pr['head']['sha'] != args.expected_head:
        raise ValueError('MERGE ANOMALY: actual parents/head differ from approval; no rollback attempted')
    target = ref(repo, pr['base']['ref'])
    source_name = 'develop' if pr['base']['ref'] == 'main' else 'main'
    source = ref(repo, source_name)
    retained_source = args.expected_head if source_name == 'develop' else pr['head']['ref'].rsplit('/', 1)[1]
    # GitHub deletes merged sync snapshot branches. Only retained trunk refs
    # participate in postconditions, and legitimate version writers may advance.
    for ancestor, descendant in [(merge, target), (retained_source, source),
                                 *[(parent, merge) for parent in parents]]:
        if ancestor == descendant:
            continue
        comparison = api(f'repos/{repo}/compare/{ancestor}...{descendant}')
        if comparison.get('merge_base_commit', {}).get('sha') != ancestor:
            raise ValueError('MERGE ANOMALY: approved history not retained; no rollback attempted')
    return {'status': 'merged', 'merge_sha': merge, 'parents': parents,
            'writer_pause': 'cooperative; no atomic expected-base lock exists'}


def merge(args: argparse.Namespace, repo: str) -> dict:
    validate_authorization(args, repo)
    pr = api(f'repos/{repo}/pulls/{args.pr}')
    kind = direction(pr, repo)
    if args.approval != f'confirm-{kind}':
        raise PolicyBlock('Consequence confirmation does not match trunk direction')
    if pr.get('merged'):
        return verify_merged(repo, pr, args)
    exact_refs(repo, pr, args)
    if collect_readiness(repo, pr)['status'] != 'ready':
        raise PolicyBlock('Readiness is blocked')
    if not final_gate(repo, args.pr, require_checks=True)['passed']:
        raise PolicyBlock('Final-gate with required checks is blocked')
    live = api(f'repos/{repo}/pulls/{args.pr}')
    if live.get('state') != 'open' or live.get('draft') or live.get('mergeable') is not True:
        raise PolicyBlock('Pull request is not open, non-draft and mergeable')
    exact_refs(repo, live, args)
    if kind == 'sync':
        validate_snapshot(repo, live)
    validate_pause(args.writers_pause_until_utc)
    payload = {'merge_method': 'merge', 'sha': args.expected_head,
               'commit_title': f'chore: {"promote develop to main" if kind == "release" else "sync main to develop"} (#{args.pr})',
               'commit_message': f'Approved base {args.expected_base}\nApproved head {args.expected_head}'}
    # A transport error is reconciled by a read. Never blindly repeat a PUT.
    try:
        response = api(f'repos/{repo}/pulls/{args.pr}/merge', payload=payload, method='PUT')
    except PolicyBlock:
        raise
    except (OSError, ValueError, subprocess.SubprocessError):
        response = {}
    live = api(f'repos/{repo}/pulls/{args.pr}')
    if not live.get('merged') and response.get('merged') is False:
        raise PolicyBlock('GitHub declined the merge; no bypass or retry attempted')
    result = verify_merged(repo, live, args)
    add_current_span_event('branch.merge.completed', {'branch.direction': kind, 'branch.status': 'merged'})
    return result


def run_pr_candidates(repo: str, run: dict) -> list[dict]:
    sha = run.get('head_sha', '')
    if not SHA.fullmatch(sha):
        raise ValueError('Invalid workflow source SHA')
    linked = run.get('pull_requests', [])
    if linked:
        candidates = [api(f'repos/{repo}/pulls/{item["number"]}') for item in linked]
    else:
        endpoints = [f'repos/{repo}/pulls?state=open&per_page=100']
        if run['name'] in {'Release', 'Release / 2 Publish'}:
            endpoints.append(f'repos/{repo}/commits/{sha}/pulls?per_page=100')
        candidates = []
        for endpoint in endpoints:
            response = branch_command([GH, 'api', '--hostname', 'github.com', endpoint]).stdout
            if len(response.encode()) > 4_000_000:
                raise ValueError('PR event lookup payload too large')
            values = json.loads(response)
            if not isinstance(values, list) or len(values) >= 100:
                raise ValueError('Ambiguous PR event lookup')
            candidates.extend(values)
    return [pr for pr in candidates if (
        pr['head']['sha'] == sha and pr['head']['ref'] == run['head_branch']
    ) or (run['name'] == 'Release' and pr.get('merged_at') is not None
          and pr.get('merge_commit_sha') == sha and pr['base']['ref'] == run['head_branch'])]


def proposal_candidates(repo: str, operation: str) -> list[dict]:
    if os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise ValueError('Proposal readiness requires trusted main')
    if operation not in {'propose-release', 'propose-sync'}:
        raise ValueError('Unsupported proposal operation')
    response = branch_command([GH, 'api', '--hostname', 'github.com',
                               f'repos/{repo}/pulls?state=open&per_page=100']).stdout
    if len(response.encode()) > 4_000_000:
        raise ValueError('Proposal payload too large')
    candidates = json.loads(response)
    if not isinstance(candidates, list) or len(candidates) >= 100:
        raise ValueError('Ambiguous proposal lookup')
    kind = 'release' if operation == 'propose-release' else 'sync'
    supported = []
    for pr in candidates:
        try:
            if direction(pr, repo) == kind:
                supported.append(pr)
        except ValueError:
            continue
    return supported


def event_prs(repo: str, name: str, path: str) -> list[int]:
    event_path = Path(path)
    if event_path.stat().st_size > 4_000_000:
        raise ValueError('Event payload too large')
    event = bounded_json(event_path.read_text())
    if event.get('repository', {}).get('full_name') != repo:
        raise ValueError('Event repository differs')
    if name in {'schedule', 'workflow_dispatch'}:
        operation = 'propose-release' if name == 'schedule' else event.get('inputs', {}).get('operation')
        candidates = proposal_candidates(repo, operation)
    elif name in {'pull_request', 'pull_request_target'}:
        if event.get('action') not in {'opened', 'reopened', 'synchronize', 'edited', 'ready_for_review', 'closed'}:
            return []
        candidates = [event['pull_request']]
    elif name == 'workflow_run':
        trigger = event['workflow_run']
        if not isinstance(trigger.get('id'), int) or trigger['id'] < 1:
            raise ValueError('Workflow event lacks run identity')
        run = api(f'repos/{repo}/actions/runs/{trigger["id"]}')
        if run.get('id') != trigger['id']:
            raise ValueError('Workflow run identity differs')
        paths = {'ci': '.github/workflows/ci.yml', 'Checks / Python': '.github/workflows/ci.yml',
                 'Release / 2 Publish': '.github/workflows/release.yml', 'Release': '.github/workflows/release.yml'}
        if (event.get('action') != 'completed' or run.get('name') not in paths
                or run.get('path') != paths[run['name']]
                or run.get('head_repository', {}).get('full_name') != repo):
            return []
        candidates = run_pr_candidates(repo, run)
    else:
        raise ValueError('Unsupported readiness event')
    supported = []
    for pr in candidates:
        try:
            direction(pr, repo)
        except ValueError:
            continue
        supported.append(pr['number'])
    return sorted(set(supported))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest='command', required=True)
    for name in ('readiness', 'merge'):
        child = commands.add_parser(name)
        child.add_argument('--repo', required=True)
        child.add_argument('--pr', type=int, required=name == 'merge')
        child.add_argument('--output-dir', type=Path, required=True)
        if name == 'readiness':
            child.add_argument('--publish-summary', action='store_true')
            child.add_argument('--event-name')
            child.add_argument('--event-file')
        else:
            child.add_argument('--expected-head', required=True)
            child.add_argument('--expected-base', required=True)
            child.add_argument('--approval', choices=['confirm-release', 'confirm-sync'], required=True)
            child.add_argument('--writers-pause-until-utc', required=True)
            child.add_argument('--actor', required=True)
    return root


def readiness(args: argparse.Namespace, repo: str) -> None:
    if args.pr:
        numbers = [args.pr]
    elif args.event_name and args.event_file:
        numbers = event_prs(repo, args.event_name, args.event_file)
    else:
        raise ValueError('Readiness needs --pr or --event-name and --event-file')
    if not numbers:
        shared.write_json(args.output_dir / 'readiness.json', {'status': 'no-candidates', 'repository': repo})
        (args.output_dir / 'readiness.md').write_text('No supported trunk pull requests require readiness.\n')
        return
    for number in numbers:
        if number < 1:
            raise ValueError('Invalid PR number')
        pr = api(f'repos/{repo}/pulls/{number}')
        result = collect_readiness(repo, pr)
        markdown = markdown_summary(result)
        destination = args.output_dir if len(numbers) == 1 else args.output_dir / str(number)
        shared.write_json(destination / 'readiness.json', result)
        (destination / 'readiness.md').write_text(markdown)
        if args.publish_summary:
            # Read the body again so concurrent human edits are not overwritten
            # using an old projection captured before CI/review collection.
            live = api(f'repos/{repo}/pulls/{number}')
            if live['head']['sha'] != pr['head']['sha'] or live['base']['sha'] != pr['base']['sha']:
                raise PolicyBlock('PR changed during summary collection')
            body = live.get('body') or ''
            updated = replace_summary(body, markdown)
            if updated != body:
                api(f'repos/{repo}/pulls/{number}', method='PATCH', payload={'body': updated})
        print(markdown)


def outcome_markdown(args: argparse.Namespace, result: dict) -> str:
    lines = [f'### Guarded {args.command}', '', f'**Status:** {result["status"]}', '']
    if result.get('reason'):
        lines.extend([result['reason'], ''])
    if result.get('merge_sha'):
        sha = result['merge_sha']
        lines.extend([f'[Verified merge commit](https://github.com/{args.repo}/commit/{sha})',
                      f'Approved parents: `{result["parents"][0]}` and `{result["parents"][1]}`.', ''])
    if REPO.fullmatch(args.repo):
        lines.extend([f'[Release Actions](https://github.com/{args.repo}/actions/workflows/release.yml)',
                      f'[Homebrew Actions](https://github.com/{args.repo}/actions/workflows/homebrew.yml)', ''])
    if result['status'] == 'merged':
        lines.append('Follow release and bottle publication in Actions; publication is advisory.')
    else:
        lines.append('Inspect the live PR and merge history before any new approval; do not blindly retry a merge.')
    lines.append('Writer pause is cooperative; GitHub has no atomic expected-base lock.')
    return '\n'.join(lines) + '\n'


def write_outcome(args: argparse.Namespace, result: dict) -> None:
    shared.write_json(args.output_dir / f'{args.command}.json', result)
    (args.output_dir / f'{args.command}.md').write_text(outcome_markdown(args, result))


def public_diagnosis(exc: Exception) -> str:
    # OS/subprocess errors may embed private runner paths or raw command data.
    if isinstance(exc, PolicyBlock):
        return str(exc)
    if isinstance(exc, ValueError) and str(exc).startswith(('MERGE ANOMALY:', 'Merge acceptance is unknown')):
        return str(exc)
    return f'Operation unavailable ({type(exc).__name__}); inspect workflow diagnostics and live repository state.'


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        repo = canonical_repository(args.repo)
        if args.command == 'readiness':
            readiness(args, repo)
        else:
            if args.pr < 1:
                raise PolicyBlock('Invalid PR number')
            result = merge(args, repo)
            write_outcome(args, result)
        return 0
    except PolicyBlock as exc:
        diagnosis = public_diagnosis(exc)
        write_outcome(args, {'status': 'blocked', 'reason': diagnosis})
        print(diagnosis, file=sys.stderr)
        return 2 if args.command == 'merge' else 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        diagnosis = public_diagnosis(exc)
        write_outcome(args, {'status': 'unknown', 'reason': diagnosis})
        print(diagnosis, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(shared.traced_main(main))
