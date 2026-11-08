// A release observation is independent of whether publication is enabled.
import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const verificationStates = new Set(['passed', 'failed', 'not-run']);
const targetStates = new Set(['completed', 'failed', 'in-progress', 'not-run', 'unknown']);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);

export function createResult(input) {
  if (!object(input) || !/^[a-f0-9]{40}$/.test(input.candidate_sha || '')) {
    throw new Error('An exact release candidate SHA is required');
  }
  if (input.schema_version !== undefined && input.schema_version !== 1) throw new Error('Unsupported result schema');
  if (typeof input.enabled !== 'boolean') throw new Error('Publication enabled must be a boolean');
  const verification = input.verification ?? 'not-run';
  if (!verificationStates.has(verification)) throw new Error('Invalid verification state');
  const targets = input.targets ?? {};
  if (!object(targets) || Object.values(targets).some(target => !object(target) || !targetStates.has(target.status))) {
    throw new Error('Each publication target needs an explicit supported state');
  }
  const version = input.version ?? null;
  if (version !== null && (typeof version !== 'string' || !/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(version))) {
    throw new Error('Invalid analyzed release version');
  }
  const states = Object.values(targets).map(target => target.status);
  const completed = states.filter(state => state === 'completed').length;
  const failed = verification === 'failed' || states.includes('failed') || Boolean(input.failure_stage);
  let publication;
  if (!input.enabled) publication = 'disabled';
  else if (completed && (failed || verification !== 'passed' || completed !== states.length)) publication = 'partial';
  else if (failed) publication = 'failed';
  else if (verification !== 'passed') publication = 'in-progress';
  else if (version === null) publication = 'no-release';
  else if (states.length && completed === states.length) publication = 'completed';
  else publication = 'in-progress';
  if (input.publication !== undefined && input.publication !== publication) {
    throw new Error('Publication state conflicts with observed verification or target results');
  }
  if (input.artifacts !== undefined && !Array.isArray(input.artifacts)) throw new Error('Artifacts must be an array');
  if (input.errors !== undefined && !Array.isArray(input.errors)) throw new Error('Errors must be an array');
  return {
    schema_version: 1,
    candidate_sha: input.candidate_sha,
    baseline_tag: input.baseline_tag ?? null,
    version,
    enabled: input.enabled,
    verification,
    publication,
    targets: structuredClone(targets),
    artifacts: structuredClone(input.artifacts ?? []),
    failure_stage: input.failure_stage ?? null,
    recovery: structuredClone(input.recovery ?? null),
    errors: structuredClone(input.errors ?? []),
  };
}

const cell = value => String(value ?? '').replaceAll('|', '\\|').replaceAll('\n', ' ').replaceAll('\r', ' ');

export function writeResult(outputPath, input, { summaryPath = process.env.GITHUB_STEP_SUMMARY } = {}) {
  const result = createResult(input);
  mkdirSync(dirname(resolve(outputPath)), { recursive: true });
  writeFileSync(outputPath, JSON.stringify(result, null, 2) + '\n');
  if (summaryPath) {
    const rows = Object.entries(result.targets).map(([name, target]) =>
      `| ${cell(name)} | ${cell(target.status)} | ${cell(target.url)} |`);
    const lines = ['## Release result', '', `Candidate: \`${result.candidate_sha}\``, '',
      `Verification: **${result.verification}**; publication: **${result.publication}**`, '',
      `Baseline: ${cell(result.baseline_tag) || 'unverified'}; version: ${cell(result.version) || 'none'}`, '',
      '| Target | State | Evidence |', '| --- | --- | --- |', ...rows, ''];
    if (result.failure_stage) lines.push(`Failed stage: ${cell(result.failure_stage)}`, '');
    for (const error of result.errors) lines.push(`- ${cell(typeof error === 'string' ? error : error.message ?? error.code)}`);
    if (result.recovery) lines.push('', `Recovery: \`operation=recover\`, \`source_run_id=${cell(result.recovery.source_run_id)}\`, \`artifact_id=${cell(result.recovery.artifact_id)}\``);
    appendFileSync(summaryPath, lines.join('\n') + '\n');
  }
  return result;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const value = flag => { const index = args.indexOf(flag); return index < 0 ? undefined : args[index + 1]; };
  const input = value('--input');
  const output = value('--output');
  if (!input || !output || args.length !== 4) throw new Error('Usage: release-result.mjs --input INPUT.json --output release-result.json');
  writeResult(output, JSON.parse(readFileSync(input, 'utf8')));
}
