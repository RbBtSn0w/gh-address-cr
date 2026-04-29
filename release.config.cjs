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
    [
      "@semantic-release/commit-analyzer",
      {
        preset: "conventionalcommits",
        parserOpts: releaseParserOpts,
      },
    ],
    [
      "@semantic-release/release-notes-generator",
      {
        preset: "conventionalcommits",
        parserOpts: releaseParserOpts,
      },
    ],
    [
      "@semantic-release/changelog",
      {
        changelogFile: "CHANGELOG.md",
      },
    ],
    [
      "@semantic-release/exec",
      {
        prepareCmd: "python3 scripts/set_package_version.py ${nextRelease.version}",
      },
    ],
    [
      "@semantic-release/git",
      {
        assets: ["CHANGELOG.md", "pyproject.toml", "src/gh_address_cr/__init__.py"],
        message: "chore(release): ${nextRelease.version} [skip ci]\n\n${nextRelease.notes}",
      },
    ],
    "@semantic-release/github",
  ],
};
