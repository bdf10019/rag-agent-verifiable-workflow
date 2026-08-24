# Architecture and failure boundaries

## Design goals

The system treats an agent as a constrained workflow, not an unconstrained process. Planning is bounded, every tool is allowlisted, evidence is server-validated, high-risk decisions pause for a person, and every transition is persisted.

## Component responsibilities

| Component | Responsibility | Explicitly does not do |
|---|---|---|
| API | Typed contracts, demo role policy, errors, health and metrics | Accept credentials, arbitrary SQL or arbitrary URLs |
| Bounded planner | Produce at most six typed steps from an incident | Execute tools or expand its own allowlist |
| Tool registry | Map four names to server-owned implementations | Load user code or shell commands |
| Tool executor | Timeout, retry, attempt audit and failure injection | Retry non-transient errors forever |
| Retrieval | Rank versioned local SOP sections | Treat retrieved text as an instruction to change policy |
| Risk calculator | Apply deterministic demo thresholds | Claim a certified equipment diagnosis |
| Verifier | Check tool coverage, evidence types and citation membership | Trust a generated citation without server evidence |
| Human gate | Record reviewer identity, decision and note | Send a message or modify an external system |
| SQLite | Persist runs, attempts, events, evidence metadata and decisions | Support active-active application replicas |

## State model

```text
submitted -> validating -> planning -> gathering_evidence -> verifying
                                                          |-> completed
                                                          |-> needs_review -> completed
                                                          |                -> cancelled
                                                          |-> failed -> resume
```

A resumed run reuses only previously successful, persisted tool results. Failed attempts remain in the trace. An idempotency key with identical input returns the original run; reusing the key for different input returns a conflict.

## Tool boundary

The request cannot provide SQL. `lookup_telemetry` and `lookup_maintenance_history` accept only typed asset and time arguments and execute parameterized, server-owned statements. `search_sop` reads indexed local sections. `calculate_risk` receives metrics already returned by the telemetry tool.

## Why the default planner is deterministic

The portfolio must run without an account, network, model download or charge. A deterministic planner proves orchestration, recovery and policy behavior in CI. A future LLM planner must produce the same `PlanStep` schema and remains downstream of the step limit and tool allowlist; a future model synthesizer remains upstream of the citation verifier and human gate.

## Scaling path

1. Replace the demo identity dependency with organization OIDC middleware.
2. Replace SQLite with PostgreSQL and claim queued work using transactions or a message broker.
3. Move the tool executor to workers with leases, heartbeats and a dead-letter queue.
4. Add a model adapter behind the typed planner or synthesizer contract, with cost, rate-limit and prompt-version records.
5. Replace lexical retrieval with a versioned embedding service and retrieval acceptance suite.
