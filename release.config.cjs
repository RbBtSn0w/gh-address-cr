const releaseNotesPattern = (noteKeywordsSelection) =>
  new RegExp(`^[\\s|*]*(${noteKeywordsSelection})[:\\s]+(\\S.*)`, "i");

const releaseParserOpts = {
  // Avoid conventional-commits-parser crashes on whitespace-only breaking-note
  // footers while still preserving standard non-empty BREAKING CHANGE notes.
  notesPattern: releaseNotesPattern,
};

module.exports = {
  branches: ["main"],
  repositoryUrl: "https://github.com/RbBtSn0w/gh-address-cr.git",
  tagFormat: "v${version}",
  plugins: [
    "./.github/release-train/commit-semantics.mjs",
    [
      "./.github/release-train/release-commit-analyzer.mjs",
      {
        preset: "conventionalcommits",
        parserOpts: releaseParserOpts,
        releaseRules: [
          { type: "refactor", release: "patch" },
        ],
      },
    ],
    [
      "./.github/release-train/release-notes-generator.mjs",
      {
        preset: "conventionalcommits",
        parserOpts: releaseParserOpts,
      },
    ],
    "./scripts/release/consistency.mjs",
    ["@semantic-release/github", {
      assets: ["dist/*.whl", "dist/*.tar.gz"],
      successComment: false,
      failComment: false,
      releasedLabels: false,
    }],
  ],
};
