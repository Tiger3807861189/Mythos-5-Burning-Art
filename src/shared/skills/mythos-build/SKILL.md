---
name: mythos-build
description: "Implement an explicitly approved feature, refactor, migration, integration, or other code change in small verified increments while preserving scope and recording deviations. Use only during Mythos lifecycle phase 9 after the current plan, criteria, baseline, paths, and side effects have valid human approval."
---

# Mythos Build

Execute the approved plan; do not redesign it silently. Read [references/implementation-notes.md](references/implementation-notes.md) before the first edit.

## Prove authority

Before mutation, verify the current run ID, plan digest, human approval, baseline fingerprint, allowed paths, permitted commands and effects, criteria, and host permissions. Stop if any value is missing, stale, or mismatched. An initial "build this" request is not approval of a later plan.

Inspect the current diff and preserve unrelated human changes. Never reset, overwrite, or reformat them away.

## Implement in bounded increments

For each approved step:

1. **Discover** the immediate code and test context.
2. **Hypothesize** the smallest change that satisfies named criteria.
3. **Act** only on approved surfaces.
4. **Verify** with the cheapest discriminating check, then the relevant test.
5. **Record** actual files, behavior, evidence, and deviation.
6. **Decide** to continue, retry with new evidence, replan, or stop.

Keep the code runnable whenever practical. Add or update tests with behavior, not after all implementation. Preserve native architecture and conventions. Do not add dependencies, migrations, public interfaces, security changes, or external effects unless explicitly approved.

Fingerprint each attempt by step, hypothesis, evidence snapshot, action, and expected observation. Never repeat a failed fingerprint. After three failures with no measurable information gain, enter `AWAITING_HUMAN_INPUT` with at most five numbered A-D questions.

## Handle discoveries and deviations

Record every plan-versus-actual difference immediately. A local implementation detail may remain within approval only if scope, architecture, public behavior, data, security, compatibility, dependencies, paths, side effects, and criteria remain unchanged.

Stop and return to discovery or planning when a new fact changes any of those boundaries. Invalidate approval. Do not hide scope expansion as cleanup.

When the human gives a mid-build direction that conflicts with evidence, show the evidence and consequence. Recommend a correction and ask for an A-D decision. Never bypass host safety even when instructed.

## Finish phase 9

Run the approved verification ladder, inspect the full diff, remove accidental artifacts, and complete implementation notes. Map every criterion to current evidence. Report unverified conditions honestly.

Return the diff summary, evidence, deviations, residual risks, and verifier packet to `$mythos-orchestrate`. Do not self-approve and do not mark `DONE`; phase 10 requires a fresh-context verifier.
## Use the durable attempt contract

Before the first substantive act, read [the canonical attempt contract](../mythos-orchestrate/references/attempt-contract.md) completely. Follow its one-act/one-packet rule, persistent pending-act gate, no-repeat fingerprint rule, three-no-gain stop, A-D wait, and explicit terminal protocol exactly. This profile Skill does not redefine that shared wire contract.