# Repair Contract

```text
Defect ID:
Causal invariant:
Root-cause evidence:
Pre-fix regression:
Approved repair boundary:
Allowed paths and effects:
Minimal change:
Post-fix regression:
Adjacent verification:
Sibling-pattern query:
Sibling results:
Compatibility evidence:
Rollback:
Deviation:
```

Reject these false repairs:

- catching or ignoring the error without restoring the invariant;
- weakening an assertion, type, validation, permission, or test;
- retrying a deterministic failure without addressing cause;
- special-casing one fixture when the causal pattern is general;
- changing defaults or public contracts without approval;
- broad refactoring that makes causal attribution unclear.

Classify outcomes as `REPAIRED_PENDING_INDEPENDENT_VERIFICATION`, `REPLAN_REQUIRED`, `AWAITING_HUMAN_INPUT`, or `BLOCKED`.
