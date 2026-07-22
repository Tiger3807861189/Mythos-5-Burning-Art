# Implementation Notes

Open one entry for each plan step:

```text
Step ID:
Plan digest:
Planned behavior:
Actual files and symbols:
Actual behavior:
Commands or tools used:
Immediate evidence:
Acceptance criteria:
Deviation: NONE | LOCAL | MATERIAL
Deviation reason:
Approval still valid: YES | NO
Risks and follow-up:
```

Maintain a deviation ledger:

```text
ID | Planned | Actual | Reason | Scope impact | Criterion impact | Disposition
```

Use dispositions `ACCEPT_WITHIN_SCOPE`, `REMOVE`, `REPLAN`, or `NEEDS_HUMAN`. A deviation is material if it changes architecture, public behavior, data, security, compatibility, dependency set, allowed surface, side effect, acceptance, or rollback.

Before returning phase 9, include submitter-observed changed-surface notes, test and check results with exit status, skipped checks and reasons, known limitations, and rollback notes. Do not submit or guess authoritative baseline/final fingerprints, the final changed-path inventory, manifests, or byte delta; the hook derives and seals those fields.

