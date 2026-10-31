/** Pure analysis adapter; Git facts and traced process execution belong to Python. */
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { analyzeCommits } from "@semantic-release/commit-analyzer";

const require = createRequire(import.meta.url);
const trustedConfig = require("../../release.config.cjs");
const cwd = fileURLToPath(new URL("../../", import.meta.url));
const stableVersion = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const fullSha = /^[a-f0-9]{40}$/;

function exactKeys(value, keys) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === keys.length
    && keys.every((key) => Object.hasOwn(value, key));
}

/** Analyze only supplied immutable commit facts using this trusted checkout's policy. */
export async function analyzeRelease(input) {
  if (!exactKeys(input, ["commits", "current_version", "baseline_tag"])
      || typeof input.current_version !== "string" || !stableVersion.test(input.current_version)
      || typeof input.baseline_tag !== "string" || !input.baseline_tag.startsWith("v")
      || !stableVersion.test(input.baseline_tag.slice(1)) || !Array.isArray(input.commits)
      || !input.commits.every((commit) => exactKeys(commit, ["hash", "message"])
        && typeof commit.hash === "string" && fullSha.test(commit.hash)
        && typeof commit.message === "string")) {
    throw new Error("Invalid release analysis input");
  }
  const plugins = trustedConfig.plugins.filter((plugin) => Array.isArray(plugin)
    && plugin[0] === "@semantic-release/commit-analyzer");
  if (plugins.length !== 1 || plugins[0][1]?.preset !== "conventionalcommits") {
    throw new Error("Unsupported trusted release analyzer policy");
  }
  // Commit text is analysis input, never telemetry or console output.
  const release_type = await analyzeCommits(plugins[0][1], {
    cwd,
    commits: input.commits,
    logger: { log() {} },
  });
  if (!["major", "minor", "patch", null].includes(release_type)) {
    throw new Error("Unsupported release analyzer result");
  }
  return { release_type, current_version: input.current_version, baseline_tag: input.baseline_tag };
}
