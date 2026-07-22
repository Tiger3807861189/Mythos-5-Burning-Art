<!-- MYTHOS-5-BURNING-ART:BEGIN -->
# Mythos 5 Burning Art Repository Contract

This repository uses Mythos 5 Burning Art for every substantive task. This file governs behavior; Codex sandbox policy, command rules, and trusted hooks remain separate controls.

## Mandatory routing

Classify every request before acting. A substantive task includes any file, configuration, dependency, lockfile, Git state, migration, deployment, database, external-system, architecture, interface, data, security, UX, test, build, debug, or repair change. A diagnosis that may lead to repair is substantive. Treat uncertainty as substantive.

Pure explanation and read-only status work may receive a recorded exemption. Otherwise invoke mythos-orchestrate before any implementation tool. Do not selectively invoke convenient Mythos skills. The orchestrator must visit the entire ledger and route every required skill.

## Complete phase ledger

Record every phase as PENDING, ACTIVE, PASS, BLOCKED, or NOT_APPLICABLE:

1. INTAKE
2. TERRITORY_DISCOVERY
3. UNKNOWNS_AND_BLINDSPOTS
4. OPTIONS_REFERENCES_OR_PROTOTYPES
5. ACCEPTANCE_CRITERIA
6. IMPLEMENTATION_PLAN
7. INDEPENDENT_PLAN_CRITIQUE
8. AWAITING_HUMAN_PLAN_APPROVAL
9. IMPLEMENTATION_LOOP
10. INDEPENDENT_VERIFICATION
11. PLAN_VS_ACTUAL_RECONCILIATION
12. EXPLANATION_AND_COMPREHENSION_CHECK
13. DONE

NOT_APPLICABLE requires a phase-specific permitted reason and evidence. A small task may pass phases quickly but may not erase them.

## Approval gate

After discovery, acceptance criteria, the implementation plan, and an independent critique are complete, stop in AWAITING_HUMAN_PLAN_APPROVAL. Present the plan and wait for explicit human approval. Do not edit files, install dependencies, run migrations, deploy, alter Git state, or cause external side effects before approval.

Use native plan review when the host offers it. First end a response with `MYTHOS_REVIEW_PACKET_V1`; the hook seals the exact planning material and returns its hash. Start a fresh critic only after sealing, and require it to echo that hash. After a bound PASS, end the final planning response with `MYTHOS_APPROVAL_BUNDLE_V1`, including the unchanged sealed fields and exact review hash. Only the approval statement displayed by the hook can open the mutation gate. A changed goal, scope, acceptance criterion, base fingerprint, consequential unknown, or implementation approach invalidates approval and returns to planning. Never fabricate, infer, or self-issue approval. The initial request is not approval of a plan that did not exist yet.

## Independent challenge

The critic and verifier must be separate agents with host-observable no-inherited-turn isolation. Launch each through the observable spawn tool with `fork_turns="none"` and the exact neutral message `Review only the hook-injected sealed packet. Do not use or request parent-session reasoning, a desired verdict, or an artifact summary.`. The hook binds this one-shot intent to the sealed packet, then requires a new matching agent ID and a distinct nested subagent transcript. They must not receive hidden reasoning, a desired verdict, or a persuasive summary; remain read-only; and never spawn agents. Each sealed packet has one terminal review result: invalid or non-PASS rejects it permanently, so seal a new packet before another review.

Use .codex/agents/mythos-plan-critic.toml before human approval and .codex/agents/mythos-verifier.toml after implementation. If credible fresh context or read-only isolation is unavailable, disclose it and stop in NEEDS_HUMAN_JUDGMENT.

## Human question packet

For consequential uncertainty, ask one to five numbered questions. Every question must use exactly:

1. **Decision title**
   - Why this matters: explain which downstream decisions change.
   - Evidence or uncertainty: state what was found and what remains unknown.
   - A. **Recommended option** — explain the benefit and tradeoff.
   - B. Alternative — explain the benefit and tradeoff.
   - C. Alternative — explain the benefit and tradeoff.
   - D. Other / provide a different constraint.
   - If unanswered: state whether work must pause or which conservative default would apply.

Translate the decision title, explanatory labels, option text, and explanations into the user's current interaction language. Preserve the numbered bold title, three-space-indented bullet structure, A-D markers, bold recommended A option, em-dash tradeoff separators for A-C, exact field order, and final waiting marker.

When stopping for an answer, output only the exact question blocks, optional blank lines between them, and one final standalone `MYTHOS_WAITING_FOR_HUMAN_V1` line. Introductory, status, or trailing prose is invalid. Do not combine decisions. Challenge vague requests with supported conventions. Challenge an over-specific request when evidence shows a material conflict; explain it and let the human choose unless safety or policy forbids the path.

## Completion and enforcement limits

Implement only through the approved build, debug, or repair route. Record deviations immediately. Before starting a verifier, emit `MYTHOS_VERIFICATION_PACKET_V1`; the hook seals the evidence and returns its hash. Require a new verifier to echo that exact hash. After a bound PASS, reconcile plan versus actual, explain the result, perform any required comprehension check, and end the final handoff with `MYTHOS_COMPLETION_BUNDLE_V1` containing the unchanged sealed evidence and verification hash. Never claim DONE while a phase, blocking finding, evidence gap, or approval invalidation remains.

Hooks are defense-in-depth, not proof of enforcement. They run only when the plugin and hook feature are enabled and the exact definition is trusted. Tool coverage varies by host version. If a hook is missing, skipped, disabled, untrusted, or unable to observe a tool, disclose the degradation and stop before relying on it for a mutation boundary.
## Exact portable enforcement boundary

The portable runtime authorizes only observable regular-file content changes inside the governed project. A path ending `/` or `\` is recursive; every other path is exact. Paths must be portable relative paths without upward traversal. `external_effects` is always `[]`. Git metadata, permission-only, link, junction, and directory-only mutations are unsupported. A non-mutating debug plan may use exact diagnostic commands with empty paths and step surfaces; it must leave no project content delta. Any nonempty command list makes hook snapshots include generated dependency, build, coverage, and cache roots, and every changed file must still be inside approved path scope.

Every hook-authorized phase-9 write or exact command opens one durable pending act. After the tool returns, it must be closed by exactly one `MYTHOS_ATTEMPT_PACKET_V1` from the execution skill before another substantive tool, replanning packet, waiting or terminal transition, or verification packet. At attempt close, the hook recomputes the observed content delta. Any unapproved path is recorded as a scope violation, invalidates approval, returns to phase 3, and must be reverted before a new review can establish a baseline. The third no-gain failure forces an A-D wait or exact `MYTHOS_TERMINAL_PACKET_V1`. A verifier packet submits only notes, increment evidence, acceptance evidence, and subject-bound deviations; the hook owns final scope, fingerprints, manifests, changed inventory, and exact before/after content delta. Every verifier non-PASS returns to phase 3 and requires a new review, fresh critic, and human approval.
<!-- MYTHOS-5-BURNING-ART:END -->
