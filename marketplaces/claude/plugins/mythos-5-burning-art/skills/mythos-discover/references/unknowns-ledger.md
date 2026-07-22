# Unknowns Ledger

Use one evidence record per important claim:

```text
ID:
Claim:
Class: OBSERVED | INFERRED | HUMAN_STATED
Evidence:
Confidence: HIGH | MEDIUM | LOW
Decision affected:
Recheck trigger:
```

Use one record per unknown:

```text
ID:
Quadrant: KNOWN_KNOWN | KNOWN_UNKNOWN | UNKNOWN_KNOWN | UNKNOWN_UNKNOWN
Question or fact:
Why it matters:
Current evidence:
Resolution action:
Owner: AGENT | HUMAN | EXTERNAL
Must resolve before phase:
Status: OPEN | RESOLVED | ACCEPTED_RISK
```

Check or justify exclusion of each blindspot category:

1. Users, callers, accessibility, and localization.
2. Retries, idempotency, concurrency, ordering, cancellation, and partial failure.
3. Empty, malformed, large, legacy, confidential, irreversible, and versioned data.
4. Process, network, filesystem, database, service, trust, tenant, package, and platform boundaries.
5. Public contracts, saved data, old clients, paths, and runtime versions.
6. Observability, rollout, rollback, recovery, limits, costs, and ownership.
7. Authentication, authorization, injection, secrets, and sandbox limits.
8. Performance, reliability, maintainability, testability, and determinism.
9. Human taste, vocabulary gaps, unstated non-goals, and acceptance authority.
10. Reference syntax whose semantics, lifecycle, ownership, or failure model do not match.

Map blast radius as:

```text
Surface -> Consumer or dependency -> Contract -> Evidence -> Failure consequence
```

Order human decisions by the amount of architecture they can invalidate.
