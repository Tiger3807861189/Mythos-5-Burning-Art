---
name: mythos-orchestrate
description: "Govern every substantive coding task through the complete Mythos 5 Burning Art lifecycle. Use for planning, building, changing, debugging, repairing, refactoring, migrating, testing, configuring, or otherwise acting on a codebase; route the task through all thirteen phases, independent review, explicit human plan approval, bounded execution loops, verification, reconciliation, and explanation."
---

# Mythos Orchestrate

Treat this skill as the mandatory entry point for substantive coding work. Do not claim that the model has Mythos 5 capabilities; use this procedure to compensate for weaker reasoning with explicit evidence, independent challenge, human decisions, and bounded loops.

Read [references/lifecycle-contract.md](references/lifecycle-contract.md) before classifying the request or changing phase state. Use its exact phase ledger and transition rules.

## Establish the run

1. Read all host and repository instructions before acting.
2. Preserve the host's sandbox, permission, plan-mode, approval, and tool-use controls. Never treat this skill as authority to bypass them.
3. Classify the request as either:
   - `SUBSTANTIVE`: any plan, diagnosis, implementation, edit, test-driven investigation, configuration change, dependency action, Git mutation, external side effect, or work that could reasonably lead to one.
   - `READ_ONLY_EXEMPT`: a pure explanation or status lookup that requires no repository investigation capable of side effects.
4. When uncertain, classify as `SUBSTANTIVE`.
5. For `READ_ONLY_EXEMPT`, record the reason and answer without fabricating a lifecycle run.
6. For `SUBSTANTIVE`, create or resume one run ledger. Record the task profile as `BUILD`, `DEBUG`, `REPAIR`, or `PLAN_ONLY`.
7. Bind the run to the current task, repository or workspace, worktree, base revision when available, working-tree fingerprint, host session, and acceptance criteria.
8. Mark every phase `PENDING`. Never delete a phase. Use `NOT_APPLICABLE` only where the lifecycle contract permits it and record task-specific evidence.

## Execute every phase in order

### 1. Intake

Restate the requested outcome, artifacts, boundaries, constraints, non-goals, risk, and current authorization. Separate the human's desired result from any proposed method.

Challenge a proposed method when repository evidence, platform behavior, safety limits, or accepted engineering practice contradict it. State the evidence and consequence. Offer a corrected recommendation. Ask for a decision only when the difference is consequential.

Treat facts supplied by the human or evaluation fixture as available evidence. If those facts already expose a consequential choice about public compatibility, data, security, architecture, scope, or acceptance, do not bury that choice behind later discovery. Ask the human immediately with the numbered A-D packet; discovery may refine evidence but must not silently select policy.

### 2. Territory discovery

Invoke `$mythos-discover`. Require a repository map, evidence ledger, convention map, and initial risk surface. Do not rely on filenames alone when behavior matters.

### 3. Unknowns and blindspots

Continue `$mythos-discover`. Require the four-part unknowns ledger and a blindspot pass. Resolve consequential unknowns with tools or ask the human using the required A-D packet. Do not convert guesses into facts.

### 4. Options, references, or prototypes

Invoke `$mythos-options`. Require mutually exclusive directions where taste, architecture, or tradeoffs remain open. Require a semantics map before porting a reference. The portable package has no preapproval executable prototype runner. Use non-mutating references or record the exact phase-4 NOT_APPLICABLE reason; never disguise production edits as a prototype. If a consequential compatibility decision pauses a port before discovery, tell the human that the decision will be followed by a source-to-target semantics map before planning.

### 5. Acceptance criteria

Invoke `$mythos-plan`. Convert the intended outcome into observable functional, failure, regression, compatibility, and evidence criteria. Obtain human decisions for consequential ambiguity.

### 6. Implementation plan

Continue `$mythos-plan`. Put high-tweak, high-blast-radius decisions first and mechanical work last. Identify exact surfaces, checks, rollback, approval scope, and conditions that invalidate the plan.

### 7. Independent plan critique

First emit the complete `MYTHOS_REVIEW_PACKET_V1` defined by `$mythos-plan`. The Stop hook seals its exact content, binds the current project fingerprint, blocks continuation, and returns `review_packet_hash`. Do not launch the critic before that hash exists.

Then launch the reviewer through the exact one-shot host-observed contract in [the lifecycle contract](references/lifecycle-contract.md): neutral prompt, dedicated reviewer type, and no inherited turns. Codex must expose `fork_turns="none"` in the spawn tool input; Claude Code must use the named custom agent, never `fork`. The hook binds the launch to the sealed hash and accepts PASS only after a new agent ID and distinct nested subagent transcript match. Do not critique the plan in the planning context. The hook injects the packet. PASS requires the exact twelve sections listed by `$mythos-plan` once each, the exact hash, and empty blocking, high, and contamination arrays.

Require the critic to attack assumptions, missing constraints, false alternatives, unsafe transitions, insufficient tests, scope errors, and simpler solutions. Record each finding and disposition. Any material revision requires a newly sealed review packet and another fresh critic.

If no genuinely independent context is available, enter `NEEDS_HUMAN_JUDGMENT` with reason `INDEPENDENT_REVIEW_UNAVAILABLE`. Never substitute same-context self-criticism.

### 8. Human plan approval

After the critic returns a bound `PASS`, present the final plan, acceptance criteria, open decisions, critic findings, risks, intended paths, side effects, and rollback. Append the exact `MYTHOS_APPROVAL_BUNDLE_V1` defined by `$mythos-plan`, including the unchanged sealed planning fields and exact `review_packet_hash`. The Stop hook verifies the binding and displays the only valid approval statement. Then stop in `AWAITING_HUMAN_PLAN_APPROVAL`.

Accept only a new, explicit human approval of the identified current plan. Do not infer approval from the initial request, silence, urgency, a prior version, or permission to inspect. Prefer the host's native plan approval. When unavailable, require the suite's exact run identifier and plan digest.

Do not edit project files, install dependencies, mutate Git state, or perform side effects before approval. The portable runtime never authorizes external-system effects and has no executable preapproval prototype runner.

Invalidate approval when the task, acceptance criteria, plan, allowed paths, side-effect scope, base fingerprint, or consequential assumptions change.

### 9. Implementation loop

After valid approval, invoke exactly one primary execution skill:

- `$mythos-build` for features, refactors, migrations, and planned code changes.
- `$mythos-debug` for evidence-driven diagnosis. Invoke `$mythos-repair` only after root-cause evidence when a fix is in scope.
- `$mythos-repair` for an already diagnosed and approved defect.
- No mutation skill for `PLAN_ONLY`; record phase 9 as `NOT_APPLICABLE` with the approved reason.

For each increment, use `Discover -> Hypothesize -> Act -> Verify -> Record -> Decide`. Every hook-authorized substantive tool invocation, including an exact diagnostic command, opens one durable pending act. After the tool returns and any read-only observation needed for evidence, emit the exact `MYTHOS_ATTEMPT_PACKET_V1` documented by the execution skill. The hook denies every further substantive tool, replanning packet, waiting or terminal transition, and verification packet until that one act is closed. The pending act survives restart and binds the tool input plus before-and-after scoped fingerprints. Never repeat a failed fingerprint.

Stop after three failed attempts with no measurable information gain. Enter `AWAITING_HUMAN_INPUT` and ask a bounded A-D question packet. Also stop immediately when a new unknown could change architecture, public behavior, data, security, scope, or acceptance; return to phase 3 or 5 and obtain a new approval. In the user-facing stop message, state that approval is invalid, name the exact re-entry phase and ledger status, and state what evidence or decision is required to resume.

### 10. Independent verification

First emit MYTHOS_VERIFICATION_PACKET_V1 as defined by the verification skill. The Stop hook checks approval, scope, criterion coverage, increment evidence, reconciled deviations, and the current fingerprint, then returns verification_packet_hash. Only then launch the fresh verifier; the hook injects the complete sealed packet and exact hash. Require exactly one textual verdict plus one strict MYTHOS_VERIFIER_RECEIPT_V1 JSON block. A verifier must not repair the source. Only a bound PASS with every criterion covered once and empty blocking/high/contamination arrays proceeds. Because sealing freezes mutation, every REPAIR, REPLAN, or VERIFICATION_INVALID verdict returns to phase 3 and requires a new review, fresh critic, and human approval before mutation.

### 11. Plan-versus-actual reconciliation

Compare every planned step, approved path, acceptance criterion, and expected side effect with the actual diff and evidence. Classify every completed item as MATCH, NECESSARY_DEVIATION, or BENEFICIAL_DEVIATION with concrete evidence. An unresolved or out-of-scope deviation cannot enter completion: repair it or invalidate approval and replan. Update durable implementation notes.

### 12. Explanation and comprehension check

Invoke `$mythos-explain`. Explain the result in human terms, show evidence, deviations, risks, limits, rollback, and ownership. For consequential changes, require an A-D comprehension check that tests actual understanding rather than agreement.

### 13. Done

Enter `DONE` only when all required phase evidence exists, independent verification returned a bound `PASS`, deviations are reconciled, approval is current, and the explanation requirement is satisfied. Append `MYTHOS_COMPLETION_BUNDLE_V1` with the exact `verification_packet_hash` and unchanged sealed verification material. The Stop hook recomputes the binding, consumes approval, and is the final DONE guard. Otherwise use an explicit non-success terminal or waiting state.

## Ask humans precisely

Ask only consequential questions that tools and repository evidence cannot answer. Do not ask the human to choose process mechanics such as which files to inspect, whether to perform discovery, whether to plan, or whether to run required checks when a safe reversible default exists. Choose those mechanics, execute authorized read-only evidence gathering, and bring back concrete comparisons. Ask about outcome, policy, taste between concrete artifacts, public compatibility, data, security, scope, or acceptance only when the answer materially changes the result.

Ask one to five questions and use this exact grammar for every item:

```text
1. **Decision title**
   - Why this matters: explain which downstream decisions change.
   - Evidence or uncertainty: state what was found and what remains unknown.
   - A. **Recommended option** — explain the benefit and tradeoff.
   - B. Alternative — explain the benefit and tradeoff.
   - C. Alternative — explain the benefit and tradeoff.
   - D. Other / provide a different constraint.
   - If unanswered: state whether work must pause or which conservative default would apply.
```

Translate the decision title, explanatory labels, option text, and explanations into the user's current interaction language. Preserve the numbered bold title, three-space-indented bullet structure, A-D markers, bold recommended A option, em-dash tradeoff separators for A-C, exact field order, and final waiting marker.

Continue sequentially through `5` when more questions are necessary. Do not change the structural roles, indentation, A-D markers, or field order; merge questions; omit or duplicate an option; add an unnumbered question; or hide an open decision in prose. Do not use a question to offload ordinary investigation. A waiting response must contain only the one-to-five question blocks, optional blank lines between blocks, and one final standalone `MYTHOS_WAITING_FOR_HUMAN_V1` line. Introductory, status, or trailing prose makes the packet invalid; place necessary evidence and state inside the required fields.

## Preserve truthful control

- Do not claim a hook, approval guard, state lock, sandbox, or fresh-context boundary exists unless the host confirms it.
- If deterministic enforcement is unavailable, say which boundary is advisory and stop before the unguarded action when the risk is material.
- Never weaken security, tests, or acceptance criteria to make the loop terminate.
- Never report `DONE` because time, tokens, or patience ran low.
## Exact non-success terminal packet

If work cannot continue, emit exactly one block and stop:

MYTHOS_TERMINAL_PACKET_V1_BEGIN
```json
{"schema_version":1,"run_id":"m5-...","terminal_state":"NEEDS_HUMAN_JUDGMENT","current_phase":"INDEPENDENT_PLAN_CRITIQUE","reason":"specific reason","evidence":{"observation":"concrete nonempty evidence"},"resume_condition":"specific condition"}
```
MYTHOS_TERMINAL_PACKET_V1_END

Use only `BLOCKED` or `NEEDS_HUMAN_JUDGMENT`. Resume with `RESUME MYTHOS RUN <run-id>: <what changed>`. An A-D wait uses `MYTHOS_WAITING_FOR_HUMAN_V1` instead and resumes on the next human answer. After the third no-gain failure, the hook rejects further tools until one of those two exact paths is used.
