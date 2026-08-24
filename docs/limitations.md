# Limitations and next work

## Current limitations

1. SQLite is a single-node portfolio store. It is not an active-active workflow database.
2. The planner and final summary are deterministic to preserve an offline, zero-cost baseline.
3. Retrieval is lexical and intended for a small original SOP collection.
4. Retry state is synchronous inside the request; production workers should use durable leases and asynchronous execution.
5. The human decision is local database state and does not create a work order, email or external notification.
6. Demo thresholds and procedures are illustrative and are not certified equipment limits.
7. Kubernetes manifests demonstrate packaging controls but have not been deployed in the current environment.

## Prioritized next work

1. PostgreSQL persistence, durable worker queue, lease expiry, dead-letter handling and concurrent-run tests.
2. OIDC identity, organization and asset-level authorization, plus append-only remote audit storage.
3. Versioned embedding service, hybrid retrieval and retrieval recall evaluation.
4. Optional model planner/synthesizer adapter with JSON schema, prompt versions, cost and deterministic fallback.
5. OpenTelemetry spans, Prometheus histograms and alert rules backed by load and chaos tests.
6. A sandboxed outbound action connector that still requires a signed approval and idempotent delivery key.
