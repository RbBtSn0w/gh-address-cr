/** Release-aware API adapter. Only semantic-release computes release versions. */
import semanticRelease from 'semantic-release';
import { analyzeCommits } from '../../.github/release-train/release-commit-analyzer.mjs';
import { generateNotes } from '../../.github/release-train/release-notes-generator.mjs';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { baseline, configDigest } from './consistency.mjs';
import {validateOriginalPlan} from '../../.github/release-train/release-entrypoint.mjs';
const root = fileURLToPath(new URL('../../', import.meta.url));
const config = createRequire(import.meta.url)('../../release.config.cjs');
const quiet = {write() {}};
function localEnvironment() {
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    ['PATH', 'HOME', 'TMPDIR', 'SYSTEMROOT'].includes(key)));
  return {...env, CI: 'true', GIT_TERMINAL_PROMPT: '0', GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null', RELEASE_TOOLS: root};
}
const git = (cwd, ...args) => execFileSync('git', ['-c', 'core.fsmonitor=false', ...args],
  {cwd, env: localEnvironment(), encoding: 'utf8'}).trim();
const absolutePlugin = (plugin) => {
  const entry = Array.isArray(plugin) ? plugin[0] : plugin;
  const name = entry.startsWith('./') ? resolve(root, entry) : entry;
  return Array.isArray(plugin) ? [name, plugin[1]] : name;
};
export async function planRelease(source = process.cwd()) {
  const temporary = mkdtempSync(join(tmpdir(), 'gh-address-cr-analysis-'));
  try {
    const mirror = join(temporary, 'mirror.git');
    const checkout = join(temporary, 'candidate');
    const candidate = git(source, 'rev-parse', 'HEAD');
    git(temporary, 'clone', '--quiet', '--mirror', source, mirror);
    git(temporary, 'clone', '--quiet', mirror, checkout);
    git(checkout, 'checkout', '--quiet', '-B', 'main', candidate);
    // Publish only to the local mirror in dry-run; no service plugins or credentials.
    git(mirror, 'update-ref', 'refs/heads/main', candidate);
    const env = localEnvironment();
    let completed = false;
    let acceptedBaseline;
    const analyzer = config.plugins.find((item) => Array.isArray(item) && item[0] === './.github/release-train/release-commit-analyzer.mjs');
    const record = async (_options, context) => {
      const type = await analyzeCommits(analyzer[1], context);
      acceptedBaseline = baseline(context.lastRelease);
      completed = true;
      return type;
    };
    const result = await semanticRelease({...config, extends: [], repositoryUrl: pathToFileURL(mirror).href, dryRun: true, ci: false,
      plugins: [], analyzeCommits: [absolutePlugin(config.plugins[0]), record],
      generateNotes: (_options, context) => generateNotes(config.plugins.find(item => Array.isArray(item) && item[0] === './.github/release-train/release-notes-generator.mjs')[1], {...context, options: {...context.options, repositoryUrl: config.repositoryUrl}})}, {cwd: checkout, env, stdout: quiet, stderr: quiet});
    if (!completed || !acceptedBaseline?.gitHead) throw new Error('Analysis incomplete or published baseline missing');
    return {completed, candidate, baseline: acceptedBaseline, config: configDigest(), version: result ? result.nextRelease.version : null, tag: result?.nextRelease?.gitTag ?? null, notes: result?.nextRelease?.notes ?? null};
  } finally { rmSync(temporary, {recursive: true, force: true}); }
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const [mode, filename] = process.argv.slice(2);
  if (!filename || !['plan', 'publish'].includes(mode)) throw new Error('Usage: engine.mjs plan|publish plan.json');
  if (mode === 'plan') {
    const plan = await planRelease();
    writeFileSync(filename, JSON.stringify(plan, null, 2) + '\n');
    console.log(JSON.stringify(plan));
    if (process.env.GITHUB_OUTPUT) writeFileSync(process.env.GITHUB_OUTPUT, `released=${!!plan.version}\nversion=${plan.version || ''}\nsource_sha=${plan.candidate}\n`, {flag: 'a'});
  } else {
    const plan = JSON.parse(readFileSync(filename, 'utf8'));
    validateOriginalPlan(plan);
    if (!plan.version || !plan.completed) throw new Error('Release plan has no completed release');
    const result = await semanticRelease({...config, plugins: config.plugins.map(absolutePlugin)},
      {env: {...process.env, RELEASE_PLAN: resolve(filename)}});
    if (!result) throw new Error('Reanalysis became no-op: stale/already released plan');
  }
}
