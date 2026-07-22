---
name: mythos-explain
description: "Reconcile and explain an independently verified code change, its evidence, deviations, risks, limits, ownership, and rollback, then test human understanding with an A-D comprehension check. Use during Mythos lifecycle phases 11 and 12 before a run may enter DONE."
---

# Mythos Explain

Make the result inspectable and transferable, not merely impressive. Read [references/handoff-and-quiz.md](references/handoff-and-quiz.md) before producing the handoff.

## Reconcile plan and reality

Compare every planned step, approved path, expected effect, and acceptance criterion with the final diff and verifier report. Classify each difference as `MATCH`, `NECESSARY_DEVIATION`, `BENEFICIAL_DEVIATION`, `UNRESOLVED`, or `OUT_OF_SCOPE`.

For each deviation, state why it occurred, evidence, risk, approval impact, and disposition. Remove accidental work or return to planning for material scope. Do not describe an unapproved change as a harmless implementation detail.

## Build human buy-in

Explain:

1. what changed in observable terms;
2. why this design was chosen over rejected alternatives;
3. how data and control flow now work;
4. which files and interfaces matter;
5. how acceptance was verified;
6. where the implementation departed from the plan;
7. known limits, risks, monitoring, rollback, and ownership;
8. what a future maintainer must not accidentally break.

Use direct evidence and compact diagrams or examples only when they improve understanding. Separate facts, inferences, and recommendations. Do not claim coverage that the verifier marked unavailable.

Pre-answer likely reviewer objections: complexity, simpler alternatives, compatibility, performance, security, migration, rollback, and maintenance burden. State whose decision or action is still needed.

## Check comprehension

For consequential changes, ask three to five numbered questions about architecture, failure behavior, invariants, rollback, and maintenance. Give four plausible options `A` through `D` under each. Do not make the correct answer obvious through length or praise.

If an answer is wrong, explain the specific misconception, point to the relevant change or evidence, and ask a focused follow-up. Do not treat agreement as understanding. A low-impact change may waive the response requirement with recorded justification; an explicit human waiver also suffices. Always provide the explanation.

## Finish honestly

Return the handoff, reconciliation table, evidence index, risks, rollback, ownership, and comprehension status to `$mythos-orchestrate`. Enter phase 13 only when the verifier passed, all deviations are resolved, approval is current, and no human decision remains. Otherwise return `AWAITING_HUMAN_INPUT`, `REPLAN_REQUIRED`, or `BLOCKED`.

