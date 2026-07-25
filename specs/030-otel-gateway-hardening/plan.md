# Implementation Plan: OTel Gateway Hardening

## Architecture Preflight

| Boundary | Decision |
|---|---|
| Authoritative state owner | CLI/runtime state remains authoritative; telemetry never becomes workflow truth |
| External inputs | CLI argv/env, subprocess final result, optional W3C parent context, gateway response |
| Projection | Stable Resource, one invocation root, approved child operations, checkpoint events |
| Policy | Subprocess argv is prohibited; operation/error values come from bounded deterministic classifiers |
| Side-effect boundary | One traces-only OTLP/HTTP exporter; no logs, metrics, or new business side effects |
| Artifact truth | Traces, boards, and canary evidence are operational outputs, never final-gate evidence |
| Recovery/replay | Export is fail-open; endpoint rollback or telemetry opt-out restores the previous network boundary |
| Self-reference risk | Export/gateway health cannot be inferred from absence of application spans alone |
| Executable contracts | In-memory privacy/resource/error/exporter tests plus staging canaries and Honeycomb queries |

## Delivery

1. Remove subprocess argv and replace it with bounded operation attribution.
2. Add stable Resource identity, endpoint precedence, gzip, queue/batch limits,
   always-on sampling, and bounded error classification.
3. Publish `otel-tracing.v2`, the profile request, acceptance evidence shape,
   migration note, and rollback rule.
4. Run repository verification, provision the operator-owned staging profile,
   execute canaries, then switch the production default only after approval.
5. Create the operations board and disabled baseline-dependent triggers; enable
   them only after seven days of production data.
