# Release artifact recovery preflight

Scope: release automation only; the installed review runtime, final-gate, leases,
and runtime telemetry contracts do not change.

- State owner: the original main release plan and immutable verified build handoff
  own candidate/version/bytes. GitHub and registry readbacks own publication facts.
- Inputs: schedule/manual main event, source run metadata, artifact ID and digest,
  original plan, candidate tag, GitHub assets and registry hashes.
- Projection: `release-result.json` separates verification from publication and
  records each target independently; Actions summary is a projection of it.
- Policy: analyze without credentials or activation; no change skips packaging;
  publishing requires activation and exact candidate verification. Recovery binds
  a same-repository same-workflow original main schedule/manual run and artifact,
  then reconciles only missing side effects using the original bytes.
- Side effects: existing two-phase GitHub/PyPI/plugin/Homebrew publishers remain
  owners. Recovery never computes a new version, rebuilds packages, retags or
  overwrites an existing different artifact.
- Artifact truth: GitHub immutable artifact provenance plus the sealed per-file
  inventory establish input identity; result reports cannot establish their own
  success. Publication is confirmed only by target readback.
- Helper execution: credentialed jobs use only the trusted checkout runtime
  through `PYTHONPATH=src`, with third-party binary dependencies. Original wheels
  remain payload bytes. Installed-bottle verification clears that override and
  publication credentials; it is a separate product acceptance boundary.
- Recovery: trusted main tools validate original candidate/tag/bytes even when
  main advances. Conflicts and unverifiable reads fail closed. A missing tag is
  not created during recovery.
- Verification: synthetic provenance rejection, inventory tamper, original-tag
  recovery, independent target results, and workflow authority contracts. No
  private upstream source fixtures or live publishing is needed.

This small release-domain boundary is necessary because re-running semantic
release after a partial publication can select a different version or become a
no-op. Reusing existing reconcilers avoids a second runtime state engine.
