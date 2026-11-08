// Report job observations; publication success never substitutes for verification.
import { readFileSync } from 'node:fs';
import { writeResult } from './release-result.mjs';
const needs = JSON.parse(process.env.RELEASE_NEEDS);
const mapping = JSON.parse(process.env.RELEASE_TARGETS);
const original = process.env.RELEASE_OPERATION === 'recover';
const source = original ? needs['recovery-input'] : needs.verify;
const outputs = source?.outputs ?? {};
const targets = Object.fromEntries(Object.entries(mapping).map(([target, job]) => [target, {
  status: ({success: 'completed', failure: 'unknown', cancelled: 'unknown', skipped: 'not-run'})[needs[job]?.result] ?? 'unknown',
  url: `${process.env.GITHUB_SERVER_URL}/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID}`,
}]));
let plan;
try { plan = JSON.parse(readFileSync('result-input/plan.json')); } catch { /* A failed plan is reported without inventing a version. */ }
const failed = Object.entries(needs).find(([, job]) => job.result === 'failure');
writeResult('release-result.json', {
  candidate_sha: outputs.source_sha || process.env.GITHUB_SHA,
  baseline_tag: plan?.baseline?.gitTag ?? null,
  version: outputs.version || plan?.version || plan?.next?.version || null,
  enabled: process.env.RELEASE_ENABLED === 'true',
  verification: source?.result === 'success' ? 'passed' : source?.result === 'failure' ? 'failed' : 'not-run',
  targets,
  artifacts: outputs.artifact_id ? [{id: outputs.artifact_id}] : [],
  failure_stage: failed?.[0] ?? null,
  recovery: {source_run_id: original ? process.env.SOURCE_RUN_ID : process.env.GITHUB_RUN_ID, artifact_id: outputs.artifact_id || null},
  errors: failed ? ['A release stage failed; inspect its logs and independent target receipts.'] : [],
});
