# Decision Artifacts

## Direction card

```text
Direction:
Core strategy:
Concrete behavior:
Constraints satisfied:
Tradeoffs and failure modes:
Operational cost:
Compatibility and migration:
Reversibility:
Evidence:
```

Merge variants that one implementation can fully adopt together; they are not mutually exclusive.

## Semantics map

```text
Reference concept | Target concept | Relationship | Lifecycle difference | Risk | PORT/ADAPT/REPLACE/OMIT
```

List boundary cases and gotchas after the map.

## Post-approval experiment specification

Do not execute this specification during phase 4.

```text
Question:
Hypotheses:
Observable discriminator:
Exact approved path or command:
Permitted local content effects:
Attempt limit:
Cleanup:
Expected decision impact:
Production assumptions still untested:
```

## Selection packet

```text
1. **Decision title**
   - Why this matters: explain which downstream decisions change.
   - Evidence or uncertainty: state what was found and what remains unknown.
   - A. **Recommended option** — explain the benefit and tradeoff.
   - B. Alternative — explain the benefit and tradeoff.
   - C. Alternative — explain the benefit and tradeoff.
   - D. Other / provide a different constraint.
   - If unanswered: state whether work must pause or which conservative default would apply.

Translate the decision title, explanatory labels, option text, and explanations into the user's current interaction language. Preserve the numbered bold title, three-space-indented bullet structure, A-D markers, bold recommended A option, em-dash tradeoff separators for A-C, exact field order, and final waiting marker.
```

For a waiting response, output only one to five exact blocks in sequential order, optional blank lines between blocks, and one final standalone `MYTHOS_WAITING_FOR_HUMAN_V1` line. Preserve the three-space indentation and exact field order. Introductory, status, or trailing prose is invalid; move necessary context into the required fields.

