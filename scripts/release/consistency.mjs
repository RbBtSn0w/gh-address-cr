/** Stateless comparison with the read-only semantic-release engine plan. */
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../../', import.meta.url));
export function configDigest() {
  const hash = createHash('sha256');
  for (const name of ['release.config.cjs', '.github/release-train/commit-semantics.mjs', '.github/release-train/release-commit-analyzer.mjs', '.github/release-train/release-notes-generator.mjs', 'scripts/release/consistency.mjs', 'scripts/release/engine.mjs', 'package-lock.json']) {
    hash.update(name).update(readFileSync(root + name));
  }
  return hash.digest('hex');
}
export function baseline(lastRelease = {}) {
  return {version: lastRelease.version || null, gitHead: lastRelease.gitHead || null, gitTag: lastRelease.gitTag || null};
}
function verifiedPlan(context) {
  const path = context.env.RELEASE_PLAN;
  if (!path) throw new Error('Verified release plan required');
  const plan = JSON.parse(readFileSync(path, 'utf8'));
  const candidate = execFileSync('git', ['rev-parse', 'HEAD'], {cwd: context.cwd, encoding: 'utf8'}).trim();
  if (!plan.completed || !plan.version || plan.candidate !== candidate || plan.config !== configDigest()
      || JSON.stringify(plan.baseline) !== JSON.stringify(baseline(context.lastRelease))
      || plan.version !== context.nextRelease.version) throw new Error('Release plan drift');
  return plan;
}
export function verifyRelease(_options, context) {
  verifiedPlan(context);
}
export function prepare(_options, context) {
  const plan = verifiedPlan(context);
  if (typeof plan.notes !== 'string' || context.nextRelease.notes !== plan.notes) {
    throw new Error('Release notes drift or original notes unavailable');
  }
}
