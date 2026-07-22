---
name: mythos-repair
description: "Apply an explicitly approved minimal repair to an evidence-established defect, add regression coverage, scan for the same causal pattern, and verify rollback safety. Use during Mythos lifecycle phase 9 after diagnosis and current human approval; do not use to guess at root cause."
---

# Mythos Repair

Repair the violated invariant, not only the visible symptom. Read [references/repair-contract.md](references/repair-contract.md) before editing.

## Verify prerequisites

Require a reproducible symptom or equivalent evidence, established causal chain, failing regression target, approved repair plan and digest, current baseline, allowed paths and effects, and valid host permission. Stop if diagnosis is speculative or approval is stale.

Preserve unrelated human changes. Do not expand a repair into opportunistic refactoring.

## Apply the minimal repair

1. Capture the failing regression before the fix when feasible.
2. Change the smallest surface that restores the violated invariant.
3. Run the narrow regression immediately.
4. Run adjacent tests and checks for affected contracts.
5. Search for the same causal pattern in sibling surfaces.
6. Repair siblings only when covered by approval; otherwise record them and replan.
7. Exercise failure, boundary, rollback, and compatibility paths.
8. Record actual changes and deviations.

Use `Inspect -> Predict -> Repair -> Verify -> Record -> Decide`. Fingerprint each attempt. Do not repeat an action against unchanged evidence. After three failures without information gain, enter `AWAITING_HUMAN_INPUT`.

## Protect the approved boundary

Invalidate approval if the repair changes architecture, public behavior beyond correction, data shape, security, dependencies, compatibility, paths, side effects, criteria, or rollback. Return to `$mythos-orchestrate` for discovery, plan, critique, and approval.

Challenge a requested workaround when evidence shows it masks the defect, weakens tests, suppresses errors, or creates data risk. Present evidence and a corrected option packet. Never delete or relax a valid regression merely to pass.

## Return repair evidence

Return before/after symptom evidence, causal invariant, changed surfaces, regression result, adjacent checks, sibling scan, deviations, risks, and rollback. Do not mark `DONE` or verify your own repair independently; phase 10 requires `$mythos-verify` in fresh context.
## Use the durable attempt contract

Before the first substantive act, read [the canonical attempt contract](../mythos-orchestrate/references/attempt-contract.md) completely. Follow its one-act/one-packet rule, persistent pending-act gate, no-repeat fingerprint rule, three-no-gain stop, A-D wait, and explicit terminal protocol exactly. This profile Skill does not redefine that shared wire contract.