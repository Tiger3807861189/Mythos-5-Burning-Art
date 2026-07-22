# Lifecycle Contract

This is the authoritative thirteen-phase ledger. Visit every phase in order; use only `PENDING`, `ACTIVE`, `PASS`, `BLOCKED`, or `NOT_APPLICABLE`, keep one active phase, attach evidence before PASS, and never erase a phase.

| ID | Phase | Required exit evidence |
|---|---|---|
| 1 | `INTAKE` | Outcome, boundaries, constraints, non-goals, authorization, profile |
| 2 | `TERRITORY_DISCOVERY` | Repository map, governing instructions, conventions, dependencies, baseline |
| 3 | `UNKNOWNS_AND_BLINDSPOTS` | Four unknown classes, blindspot scan, resolved consequential questions |
| 4 | `OPTIONS_REFERENCES_OR_PROTOTYPES` | Compared options or exact policy-bounded N/A evidence |
| 5 | `ACCEPTANCE_CRITERIA` | Observable success, failure, regression, compatibility, and evidence criteria |
| 6 | `IMPLEMENTATION_PLAN` | Exact protocol steps, paths, commands, checks, rollback, invalidators |
| 7 | `INDEPENDENT_PLAN_CRITIQUE` | Hook-sealed packet and host-verified fresh critic receipt |
| 8 | `AWAITING_HUMAN_PLAN_APPROVAL` | Exact human approval bound to the current bundle |
| 9 | `IMPLEMENTATION_LOOP` | Durable attempt packets and immediate evidence, or plan-only N/A |
| 10 | `INDEPENDENT_VERIFICATION` | Hook-sealed byte delta and host-verified fresh verifier receipt |
| 11 | `PLAN_VS_ACTUAL_RECONCILIATION` | Every plan step and changed path bound to a classified subject |
| 12 | `EXPLANATION_AND_COMPREHENSION_CHECK` | Handoff, risks, rollback, limits, comprehension evidence |
| 13 | `DONE` | Current approval, exact PASS evidence, no blocker, consumed authority |

Phase 4 N/A is accepted only with a runtime-permitted code and exact evidence keys. The portable package has no executable preapproval prototype runner. Phase 9 N/A is accepted only for `plan_only`. A non-mutating debug run keeps phase 9 active, records diagnostic attempts, and must produce no content delta.

## Re-entry and approval invalidation

Every reapproval restarts at `UNKNOWNS_AND_BLINDSPOTS`; phase 5 or phase 6 cannot be used as a selective shortcut. Invalidate approval when outcome, criteria, architecture, public behavior, data, security, dependencies, compatibility, exact paths, commands, method, or baseline assumptions change. A verifier non-PASS also returns to phase 3 because the sealed snapshot remains frozen.

After approval, every substantive tool boundary is checked against the hook-observed scoped fingerprint. Each hook-authorized write or exact command atomically opens one durable pending act with a unique act ID, tool-input hash, and before-act fingerprint. After the tool returns, exactly one attempt packet must close that act before another substantive tool, replanning packet, waiting or terminal transition, or verification packet. Read-only evidence collection remains available while the act is pending. The pending boundary survives restart. The third consecutive failed attempt with no gain triggers a hard stop; do not use another tool until an A-D wait or terminal packet is accepted.
When the host emits `PermissionRequest` after `PreToolUse`, it is not another act. The runtime permits only an exact continuation bound to the same tool name, input hash, and host tool-use ID, then returns neutral control so native permission remains authoritative. A mismatch or orphan permission request is denied. Native denial closes the already-open act through a truthful failed attempt packet stating that the tool did not run.

## Fresh challenge

A critic or verifier must be a distinct named reviewer with no inherited turns. Before spawning it, the host-observed tool request must carry exactly this neutral prompt: `Review only the hook-injected sealed packet. Do not use or request parent-session reasoning, a desired verdict, or an artifact summary.`

On Codex, the observable spawn request must also set `fork_turns="none"`. On Claude Code, use the dedicated named custom subagent and never `fork`. The hook binds that one-shot launch request to the sealed packet, then requires a new agent ID and a distinct host-generated `agent_transcript_path` nested under the parent transcript's `subagents/` directory. A matching agent ID alone is insufficient. The hook seals one terminal result per packet: an invalid or non-PASS result rejects that packet, and no later reviewer may overwrite it with PASS. Seal a new packet before trying again. If the hook cannot prove this chain, use `NEEDS_HUMAN_JUDGMENT` with reason `INDEPENDENT_REVIEW_UNAVAILABLE`.

## Waiting and terminal states

Use only:

- `AWAITING_HUMAN_INPUT` after a valid numbered A-D packet and `MYTHOS_WAITING_FOR_HUMAN_V1`;
- `NEEDS_HUMAN_JUDGMENT` when intent, independence, enforcement, or evidence needs a human;
- `BLOCKED` when a concrete dependency, permission, or external fact prevents progress;
- `DONE` only through the completion guard.

An A-D wait resumes automatically on the next human answer. `AWAITING_HUMAN_PLAN_APPROVAL` is both phase 8 and an explicit waiting terminal state; only the exact hook-issued approval or human plan feedback resumes it. `BLOCKED`, `NEEDS_HUMAN_JUDGMENT`, and `VERIFICATION_FAILED` resume only when the human sends `RESUME MYTHOS RUN <run-id>: <what changed>`. Preserve the exact reason, evidence, and resume condition.

## Completion invariants

DONE requires current human approval; no pending substantive act; hook-derived actual paths within exact-file or trailing-slash recursive scope; an attempt per substantive act and a passing attempt per non-plan-only step; PASS evidence for every criterion; complete plan-step and changed-path reconciliation; exact hook-derived before/after content delta; one fresh verifier receipt bound to the sealed packet; empty blocking, high, and contamination arrays; current fingerprints and instruction manifest; explanation and comprehension evidence; and no bypass of native host controls.
