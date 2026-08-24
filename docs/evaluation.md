# Evaluation strategy

## Release questions

The acceptance suite answers whether the workflow selected all required tools, reached the expected gate, assigned the deterministic risk class, and returned at least one server-validated citation. It does not claim to measure real model intelligence.

## v1 metrics

| Metric | Meaning |
|---|---|
| Case pass rate | All expected status, risk, tool and citation checks pass |
| Tool coverage | Every case executed its required allowlisted tools successfully |
| Citation presence | A recommendation includes evidence from the current run |
| Recovery behavior | An injected transient failure is retried and retained in the trace |
| Idempotency | Identical keys return one run; conflicting payloads are rejected |
| Human gate correctness | High risk cannot complete before a reviewer decision |

Run:

```powershell
opsflow evaluate --output outputs/evaluation-report.json
python -m pytest tests/test_workflow.py
```

## Dataset boundary

The three acceptance cases and all SOP text are original fixtures. The optional UCI adapter has separate schema and idempotency tests. No evaluation number from the fixture is presented as a production safety or predictive-maintenance result.

## Future model evaluation

If a live model planner or synthesizer is added, release gates should also cover tool-selection precision, argument-schema validity, grounded citation entailment, refusal accuracy, repeated-sample variance, p95 latency, token usage, cost and prompt-injection resistance. Security and human-gate failures remain hard failures that cannot be offset by another score.
