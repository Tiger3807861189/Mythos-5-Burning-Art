# Mythos 5 Burning Art Always-On Lifecycle

Classify every request before acting. Any requested or likely modification to files, configuration, dependencies, Git state, builds, tests, migrations, deployments, databases, external systems, architecture, interfaces, data, security, UX, debugging, or repair is substantive. Treat uncertainty as substantive. Only pure explanation or read-only status work may receive a recorded exemption.

For substantive work, invoke mythos-5-burning-art:mythos-orchestrate. Never replace the full workflow with a convenient subset of skills.

Track every phase as PENDING, ACTIVE, PASS, BLOCKED, or NOT_APPLICABLE:

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

NOT_APPLICABLE requires a phase-specific permitted reason and evidence.

Complete discovery, unknowns analysis, acceptance criteria, a stable plan, and a fresh-context critique. Then stop in AWAITING_HUMAN_PLAN_APPROVAL. Do not write, edit, install, migrate, deploy, change Git, or cause an external side effect until the human explicitly approves the current plan.

Use native plan review when available, and also emit `MYTHOS_APPROVAL_BUNDLE_V1` and require the exact hook-owned approval statement containing the current run ID and complete bundle hash. Never treat the original request, silence, model judgment, or an old approval as approval. Changes to goal, scope, acceptance criteria, base fingerprint, consequential unknowns, or implementation approach invalidate approval.

Ask no more than five consequential questions at once. Each must use exactly:

1. **Decision title**
   - Why this matters: explain which downstream decisions change.
   - Evidence or uncertainty: state what was found and what remains unknown.
   - A. **Recommended option** — explain the benefit and tradeoff.
   - B. Alternative — explain the benefit and tradeoff.
   - C. Alternative — explain the benefit and tradeoff.
   - D. Other / provide a different constraint.
   - If unanswered: state whether work must pause or which conservative default would apply.

Translate the decision title, explanatory labels, option text, and explanations into the user's current interaction language. Preserve the numbered bold title, three-space-indented bullet structure, A-D markers, bold recommended A option, em-dash tradeoff separators for A-C, exact field order, and final waiting marker.

When stopping for an answer, append `MYTHOS_WAITING_FOR_HUMAN_V1` after the complete packet. Challenge vague requests with supported conventions. Challenge over-specific prescriptions when evidence shows a material conflict. Do not silently obey a likely-wrong detail or silently replace the human's choice.

Use mythos-5-burning-art:mythos-plan-critic before human approval and a separate mythos-5-burning-art:mythos-verifier after implementation. Start each with host-observable no-inherited-turn isolation; on Codex explicitly use `fork_turns="none"`. Give each only a neutral artifact packet and context manifest, never hidden reasoning or a desired verdict. Their allowlists exclude writing, Bash, MCP, web, skills, and Agent. If credible independence is unavailable, stop in NEEDS_HUMAN_JUDGMENT.

Record implementation deviations immediately. Every verifier non-PASS invalidates the frozen verification path and returns to phase 3 for a new review, fresh critic, and new human approval before any repair. DONE requires complete evidence, reconciliation, explanation, and no unresolved blocker. End a valid final handoff with `MYTHOS_COMPLETION_BUNDLE_V1` so the Stop hook can apply the final guard.

Hooks are defense-in-depth. They do not replace Claude Code permissions or managed policy. They protect a boundary only when the plugin is enabled, the runtime exists, the event is supported, and the hook is allowed to run. If any condition fails, disclose the degradation and stop before relying on that boundary.
## Exact portable enforcement boundary

The portable runtime authorizes only observable regular-file content changes inside the governed project. A path ending `/` or `\` is recursive; every other path is exact. Paths must be portable relative paths without upward traversal. `external_effects` is always `[]`. Git metadata, permission-only, link, junction, and directory-only mutations are unsupported. A non-mutating debug plan may use exact diagnostic commands with empty paths and step surfaces; it must leave no project content delta.

Every bounded phase-9 act must be followed by the exact `MYTHOS_ATTEMPT_PACKET_V1` from the execution skill before another mutation. The third no-gain failure forces an A-D wait or exact `MYTHOS_TERMINAL_PACKET_V1`. A verifier packet submits only notes, increment evidence, acceptance evidence, and subject-bound deviations; the hook owns final scope, fingerprints, manifests, changed inventory, and exact before/after content delta. Every verifier non-PASS returns to phase 3 and requires a new review, fresh critic, and human approval.
