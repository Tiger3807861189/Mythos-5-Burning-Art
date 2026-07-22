---
name: mythos-options
description: "Turn unresolved design, architecture, interface, taste, or reference-port questions into concrete alternatives, semantic mappings, and non-executable experiment specifications. Use during Mythos lifecycle phase 4 when a consequential choice must be compared before acceptance criteria and planning."
---

# Mythos Options

Make choices visible before wiring them into production. Read [references/decision-artifacts.md](references/decision-artifacts.md) before creating a decision artifact.

## Select the artifact

- Use mutually exclusive directions when several coherent outcomes could satisfy the request.
- Use a terminology ladder when the human recognizes quality but lacks words for it.
- Use a semantics map before porting code, configuration, UI, or architecture.
- Use an intervention brainstorm when a symptom has several leverage points.
- Specify a reversible post-approval experiment when read-only evidence cannot resolve behavior, feasibility, performance, interaction, or taste. Do not execute it during phase 4.
- Mark phase 4 NOT_APPLICABLE only when discovery proves no material choice exists. Supply all three fields: a stable nonempty code, a concrete reason, and a nonempty task-specific evidence object. Never rely on a generated fallback.

## Compare real alternatives

Name the decision and shared constraints. Produce three or four coherent directions when feasible. Vary governing strategy, not incidental details. For each direction, show concrete behavior, tradeoffs, failure modes, operational cost, compatibility, reversibility, and needed evidence. Recommend one with evidence; do not pretend equality.

If the human's proposed direction conflicts with evidence, state the consequence and include a corrected choice. Follow an informed choice only when safe and authorized.

Teach vocabulary through contrasts: show compact examples, name changed dimensions, ask which is recognizable, then convert the answer into observable criteria.

## Port meaning, not syntax

Identify the reference's promise and invariants. Map each reference concept to the target. Record lifecycle, ownership, concurrency, errors, security, and data-shape differences. Mark each item `PORT`, `ADAPT`, `REPLACE`, or `OMIT`. Reject line-by-line copying when semantics differ.

## Specify experiments without executing them

The portable package has no preapproval executable prototype runner. During phase 4, use repository reads, references, and static comparisons only. If execution is the only credible discriminator, write a reversible experiment specification as a bounded first implementation increment: question, hypotheses, observable decision rule, exact approved path or command, permitted effects, attempt limit, cleanup, and escalation condition. It may run only after the complete plan is criticized and explicitly approved. Never disguise a production edit as a prototype.

Run `Frame -> Generate -> Contrast -> Specify -> Record -> Decide`. Stop when evidence selects a direction, the human chooses, or three cycles add no discriminating evidence. If the choice remains consequential, enter `AWAITING_HUMAN_INPUT` with one to five exact numbered A-D questions.

Return the decision, rejected alternatives, semantic map, experiment specification or read-only evidence, remaining unknowns, and acceptance consequences to `$mythos-orchestrate`. Do not implement.

