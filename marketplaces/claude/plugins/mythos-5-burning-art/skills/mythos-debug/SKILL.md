---
name: mythos-debug
description: "Diagnose reproducible or intermittent software failures with competing hypotheses, discriminating experiments, evidence updates, and explicit stop rules. Use for bug reports, failing tests, crashes, regressions, performance anomalies, and incorrect behavior within a Mythos DEBUG or REPAIR lifecycle; do not mutate production code without an approved repair plan."
---

# Mythos Debug

Find the causal mechanism, not a plausible edit. Read [references/hypothesis-ledger.md](references/hypothesis-ledger.md) before testing hypotheses.

## Establish the symptom

Record expected behavior, observed behavior, environment, frequency, first known occurrence, impact, and evidence source. Reproduce with the smallest safe case. Preserve raw output and distinguish a failed reproduction from proof that the bug is absent.

Trace the relevant execution path and identify the last known-good state and first incorrect state. Check existing tests, recent changes, configuration, data, platform differences, concurrency, and external dependencies.

## Compete hypotheses

Create at least two plausible hypotheses when evidence allows. Include a null or environmental hypothesis for intermittent failures. For each, state mechanism, supporting and contradicting evidence, predicted observation, and cheapest discriminating experiment.

Run the experiment that best separates hypotheses, not the easiest command. Update probabilities from evidence. Do not patch merely to see whether symptoms disappear when a read-only or isolated experiment can discriminate more cleanly.

Run `Observe -> Hypothesize -> Experiment -> Verify -> Record -> Decide`. Fingerprint symptom, evidence, hypothesis, experiment, and expected result. Never repeat a failed fingerprint. After three cycles with no information gain, enter `AWAITING_HUMAN_INPUT` with an A-D packet.

## Control mutation

Diagnostic reads and authorized test execution remain subject to host controls. Do not edit production code, tests, configuration, dependencies, data, or Git state unless the current approved plan expressly permits that diagnostic mutation.

If evidence establishes a root cause and a fix is in scope, produce the causal chain, counterfactual evidence, affected siblings, regression-test target, risk, and minimal repair boundary. Invoke `$mythos-repair` only after `$mythos-orchestrate` confirms valid repair approval.

If the human prescribes a fix contradicted by evidence, explain why it masks the symptom or creates risk, recommend the evidence-based path, and ask for an A-D decision. Do not knowingly implement a false fix.

## Return diagnosis

Return reproduction status, causal chain or ranked hypotheses, experiment ledger, eliminated causes, unresolved unknowns, affected surface, minimal repair boundary, and required regression evidence. Use `ROOT_CAUSE_ESTABLISHED`, `PARTIAL_DIAGNOSIS`, `NOT_REPRODUCED`, or `BLOCKED`; never overstate certainty.
## Use the durable attempt contract

Before the first substantive act, read [the canonical attempt contract](../mythos-orchestrate/references/attempt-contract.md) completely. Follow its one-act/one-packet rule, persistent pending-act gate, no-repeat fingerprint rule, three-no-gain stop, A-D wait, and explicit terminal protocol exactly. This profile Skill does not redefine that shared wire contract.