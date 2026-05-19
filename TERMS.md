# Terms of Use

`gh-address-cr` is provided as a developer tool for coordinating pull request
review-resolution workflows. It is not a ChatGPT Apps SDK app, hosted service,
or managed GitHub integration.

By using the runtime, skill, or plugin package, you are responsible for:

- reviewing commands before running them in repositories you do not control
- ensuring your local `gh` authentication has the intended repository access
- understanding that accepted runtime actions may post GitHub replies or resolve
  GitHub review threads
- verifying `gh-address-cr final-gate <owner/repo> <pr_number>` before claiming
  a PR review session is complete
- complying with your organization's policies for source code, pull requests,
  telemetry, and AI-assisted development

The project is distributed under the MIT license. See `LICENSE` for the full
license text.

The Codex plugin wrapper is a packaging layer for the existing skill. It does
not create an MCP server, ChatGPT UI, or OpenAI-hosted application.
