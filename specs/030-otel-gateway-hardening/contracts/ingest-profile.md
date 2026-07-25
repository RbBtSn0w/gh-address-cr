# Gateway Admission Contract

```yaml
contractID: otel-gateway-client/v2
profileID: anonymous-client-v1
trustClass: anonymous
allowedSignals: [traces]
gatewayBaseURL: https://telemetry-gateway.hamiltonsnow.workers.dev
approvedGatewayOrigins:
  - https://telemetry-gateway-development.hamiltonsnow.workers.dev
  - https://telemetry-gateway-staging.hamiltonsnow.workers.dev
  - https://telemetry-gateway.hamiltonsnow.workers.dev
maxBodyBytes: 262144
ratePolicyRef: anonymous-default
```

The profile describes admission policy only. It is not authentication and does
not contain a product, deployment environment, dataset, backend, credential,
or Secret binding. The gateway operator maps it to an isolated destination.

No credential or upstream routing secret belongs in this repository.

## Staging acceptance

The acceptance record must prove:

1. A successful invocation reaches only the assigned untrusted destination.
2. An expected Status-to-Action result remains non-error telemetry.
3. An unexpected failure carries bounded span error fields without raw
   exception messages or OTel Logs.
4. Gateway unavailability and rate limiting do not change business exit
   semantics.
5. No subprocess argv, payload, repository/thread identity, reply body, path,
   stream content, credential, or hash derived from subprocess values is
   present. The root span retains only the separately approved hashed VCS
   repository attribute.
6. A spoofed profile cannot reach a trusted staging or production destination.

## Production switch gate

The application default already targets the approved public gateway. Trusted
staging or production routes remain unavailable to this anonymous profile.
Route, identity, destination, and Secret changes require a separate operator
approval and rollback plan.

## Rollback

On privacy, routing, rejection, or latency regression:

1. Stop rollout and enable the supported telemetry opt-out when immediate
   containment is required.
2. Restore the previously approved application endpoint/profile.
3. Preserve CLI business behavior and collect only public-safe diagnostics.
4. Review retention for affected telemetry before resuming.
