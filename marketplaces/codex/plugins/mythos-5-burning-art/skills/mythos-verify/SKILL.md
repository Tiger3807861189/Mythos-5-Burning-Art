---
name: mythos-verify
description: "Independently falsify an implementation, diagnosis, or plan-only result against the original request, approved plan, hook-derived content delta, acceptance criteria, and raw evidence. Use during Mythos phase 10 in a verified fresh read-only context."
---

# Mythos Verify

Read [references/verification-report.md](references/verification-report.md) completely before producing a verification packet or verdict.

## Seal observable evidence first

The implementer emits `MYTHOS_VERIFICATION_PACKET_V1` with only the submitted fields documented in the reference. The submitter never supplies final scope, final fingerprint, manifests, or content delta. The hook derives those values from its approval-time byte snapshot and current byte snapshot, rejects unapproved changed paths, requires one passing durable attempt per plan step except `plan_only`, freezes the snapshot, and returns `verification_packet_hash`.

The sealed verifier packet contains the original request, applicable instructions, approved plan and criteria, approval hash, base and final fingerprints, changed-file inventory, exact hook-derived before/after content delta using UTF-8 or base64, implementation notes, reconciled subjects, raw evidence, and context manifest. Inspect the delta and current files; do not trust the implementation summary as proof.

Launch a distinct agent only after sealing, using the exact one-shot procedure in [the lifecycle contract](../mythos-orchestrate/references/lifecycle-contract.md). The observable launch intent, dedicated type, neutral prompt, new agent ID, nested transcript, and sealed hash must all bind. If the hook cannot verify the chain, return `VERIFICATION_INVALID` and enter `NEEDS_HUMAN_JUDGMENT`; never use same-context self-verification.

The verifier is read-only. It must not edit, repair, install, mutate Git, invoke external systems, spawn another agent, or weaken checks. It may inspect the sealed delta and repository with allowed read tools.

## Falsify the result

1. Reconstruct the human outcome from `original_request`.
2. Compare every hook-derived changed path and byte delta with approved scope.
3. Cover every acceptance criterion exactly once with direct evidence.
4. Test claims against failure paths, compatibility, security, concurrency, rollback, and sibling behavior as risk requires.
5. Compare each `PLAN_STEP` reconciliation subject and every hook-observed `PATH` subject with the actual delta.
6. Separate observations, inferences, and unavailable evidence.

A PASS requires exactly one textual `Verdict: PASS` and one strict receipt bound to the sealed hash. Every criterion must appear once with `PASS`; scope and approval must be true; blocking, high, and contamination arrays must be empty.

## Route non-PASS conservatively

- `PASS`: all criteria and scope claims are directly supported.
- `REPAIR`: a criterion is disproved but the intended correction appears bounded.
- `REPLAN`: scope, acceptance, architecture, data, security, dependencies, compatibility, or method must change.
- `VERIFICATION_INVALID`: packet, evidence, permissions, environment, or independence is insufficient.

The portable runtime freezes mutation after sealing and has no same-approval repair re-entry. The hook adjudicates the reviewer output at `SubagentStop` and seals one immutable terminal result for that packet. An invalid or non-PASS result rejects the packet; a later reviewer cannot overwrite it with PASS. Therefore every non-PASS verdict invalidates the frozen verification path and returns to phase 3 for a new review packet, fresh critic, and new human approval before any repair. Do not follow older instructions that route directly to phase 9.

Never mark DONE. Only a bound PASS permits reconciliation, explanation, and the completion bundle.
