import assert from "node:assert/strict";
import test from "node:test";
import { analyzeRelease } from "../scripts/release/analyze_branch_release.mjs";

const input = (messages) => ({
  commits: messages.map((message, index) => ({
    hash: (index + 1).toString(16).padStart(40, "0"),
    message,
  })),
  current_version: "3.17.0",
  baseline_tag: "v3.17.0",
});

test("official conventionalcommits analyzer uses trusted release rules", async () => {
  for (const [message, release_type] of [
    ["fix: preserve reply evidence", "patch"],
    ["refactor: simplify evidence projection", "patch"],
    ["feat: add deterministic intake", "minor"],
    ["feat!: remove legacy protocol", "major"],
    ["fix: change protocol\n\nBREAKING CHANGE: old payloads are rejected", "major"],
    ["fix: avoid parser crash\n\nBREAKING CHANGE:   ", "patch"],
    ["docs: clarify usage", null],
    ["   ", null],
  ]) {
    assert.deepEqual(await analyzeRelease(input([message])), {
      release_type, current_version: "3.17.0", baseline_tag: "v3.17.0",
    });
  }
});

test("all unreleased commits contribute and the highest release wins", async () => {
  assert.equal((await analyzeRelease(input([
    "feat!: unreleased stable-branch change", "fix: candidate change",
  ]))).release_type, "major");
  assert.equal((await analyzeRelease(input([]))).release_type, null);
});

test("official analyzer cancels a reverted unreleased commit", async () => {
  const facts = input(["feat: add temporary behavior"]);
  facts.commits.unshift({
    hash: "f".repeat(40),
    message: `revert: feat: add temporary behavior\n\nThis reverts commit ${facts.commits[0].hash}.`,
  });
  assert.equal((await analyzeRelease(facts)).release_type, null);
});

test("malformed facts and candidate policy overrides fail closed", async () => {
  const valid = input(["fix: preserve evidence"]);
  for (const invalid of [
    null,
    { ...valid, options: { releaseRules: [{ release: "major" }] } },
    { ...valid, current_version: "3.17.0-beta.1" },
    { ...valid, baseline_tag: "main" },
    { ...valid, commits: [{ hash: "main", message: "fix: invalid revision" }] },
    { ...valid, commits: [{ hash: "a".repeat(40), message: 42 }] },
    { ...valid, commits: [{ ...valid.commits[0], config: "candidate.js" }] },
  ]) {
    await assert.rejects(analyzeRelease(invalid), /Invalid release analysis input/);
  }
});
