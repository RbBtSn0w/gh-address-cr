// Remote receipts, never job success, establish channel completion.
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {writeResult} from '../../.github/release-train/release-result.mjs';
import {inspectReportPlan} from '../../.github/release-train/release-entrypoint.mjs';
const read = name => {try {return JSON.parse(readFileSync(name));} catch {return null;}};
const needs = JSON.parse(process.env.RELEASE_NEEDS);
const config=JSON.parse(readFileSync(fileURLToPath(new URL('../../.github/release-train.json',import.meta.url))));
const jobs=JSON.parse(process.env.RELEASE_TARGETS||'{}');
const defaults={stable_tag:'publish',github:'publish',pypi:'publish-pypi',homebrew:'publish-homebrew',marketplace:'publish-plugin-marketplace'};
const original = process.env.RELEASE_OPERATION === 'recover';
const source = original ? needs['recovery-input'] : needs.verify;
const outputs = source?.outputs ?? {};
const plan = read('result-input/plan.json');
const {original:originalPlan}=inspectReportPlan(plan);
const intended=originalPlan?.pipeline.goals.map(goal=>goal.id)??config.intended_targets;
const mapping=Object.fromEntries(intended.map(name=>[name,jobs[name]||defaults[name]]));
const candidate = outputs.source_sha || plan?.candidate || process.env.GITHUB_SHA;
const version = outputs.version || plan?.version || null;
const active = process.env.RELEASE_ENABLED === 'true';
const attempted = Object.values(mapping).some(job => ['success','failure','cancelled'].includes(needs[job]?.result));
const targets = Object.fromEntries(Object.keys(mapping).map(name => [name, {status: attempted ? 'unknown' : 'not-run', reason: attempted ? 'No matching remote receipt' : active ? 'Publication not required or validation did not pass' : 'Publication disabled'}]));
const matches = receipt => receipt?.candidate_sha === candidate && receipt.version === version && Number.isFinite(Date.parse(receipt.observed_at)) && (receipt.remote_id || receipt.url);
const github = read('publication-input/github-observation.json');
for(const name of ['stable_tag','github'])if(matches(github?.targets?.[name]))targets[name]=github.targets[name];
const pypi = read('publication-input/pypi-receipt.json');
const handoff=read('result-input/handoff.json');
const expected=Object.fromEntries(Object.entries(handoff?.files||{}).filter(([name])=>name.endsWith('.whl')||name.endsWith('.tar.gz')));
const files = pypi?.files ?? {};
const names = Object.keys(files);
if (handoff?.candidate===candidate && Object.keys(expected).length===2 && pypi?.candidate === candidate && pypi.version === version && names.length === 2 && names.some(name => name.endsWith('.whl')) && names.some(name => name.endsWith('.tar.gz')) && pypi.expected_files && JSON.stringify(Object.keys(pypi.expected_files).sort()) === JSON.stringify(names.sort()) && names.every(name => files[name].status === 'verified' && /^[a-f0-9]{64}$/.test(files[name].sha256) && files[name].sha256 === pypi.expected_files[name] && files[name].sha256===expected[name]) && Number.isFinite(Date.parse(pypi.observed_at))) {
  targets.pypi = {status: 'completed', candidate_sha: candidate, version, observed_at: pypi.observed_at, remote_id: `gh-address-cr/${version}`, url: `https://pypi.org/project/gh-address-cr/${version}/`, files};
}
for (const name of ['homebrew','marketplace']) {
  const receipt = read(`publication-input/${name}-receipt.json`);
  if (matches(receipt)) targets[name] = receipt;
}

const downloads=JSON.parse(process.env.REPORT_DOWNLOADS||'{}');
const downloadFailure=Object.values(downloads).some(step=>step.outcome==='failure');
const failed = Object.entries(needs).find(([, job]) => ['failure','cancelled'].includes(job.result));
const result=writeResult('release-result.json', {
  schema_version: 2, candidate_sha: candidate, baseline_tag: plan?.baseline?.gitTag ?? null, version,
  analysis: plan?.completed === true && plan.candidate === candidate ? (version ? 'release' : 'no-release') : 'failed',
  enabled: active, verification: source?.result === 'success' ? 'passed' : source?.result === 'failure' ? 'failed' : 'not-run',
  intended_targets: Object.keys(mapping), targets, concluded: true,
  artifacts: outputs.artifact_id ? [{id: outputs.artifact_id}] : [],
  failure_stage: downloadFailure?'report-input':failed?.[0]??null,
  recovery: read('publication-input/recovery-availability.json'),
  errors: [...(downloadFailure?['Report artifact download failed; channel receipts remain unconfirmed.']:[]),...(github?.errors||[]),...(failed?[`${failed[0]} ${failed[1].result}; inspect its named step and channel evidence.`]:[])],
}, {config,plan});

if(downloadFailure||result.verification==='failed'||result.failure_stage||(active&&['failed','partial'].includes(result.publication)&&!result.asynchronous)) {
  console.error('::error::Release verification or publication is incomplete. Inspect Release outcome and the original channel receipts.');
  process.exitCode=1;
}
