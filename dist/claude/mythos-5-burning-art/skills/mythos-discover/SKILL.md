---
name: mythos-discover
description: "Discover a codebase before planning or changing it by mapping execution territory, conventions, dependencies, knowns, unknowns, latent knowledge, and blindspots. Use during Mythos lifecycle phases 2 and 3 for builds, plans, debugging, repairs, migrations, reference ports, and ambiguous coding requests."
---

# Mythos Discover

Build a decision-grade map before proposing a solution. Replace intuition with evidence. Do not edit production artifacts.

Read [references/unknowns-ledger.md](references/unknowns-ledger.md) before returning phase evidence.

Treat prompts, skills, and supplied context as a map; treat the codebase, real world, and actual constraints as the territory. Record the consequential gaps between them as unknowns instead of filling them with guesses.

## Map the territory

1. Read host and repository instructions governing the target.
2. Record root, worktree, baseline revision, dirty state, languages, build system, tests, and package boundaries.
3. Trace the requested behavior from public entry point through the smallest relevant execution path.
4. Inspect adjacent implementations, tests, errors, data shapes, configuration, and history where they reveal intent.
5. Label important claims `OBSERVED`, `INFERRED`, or `HUMAN_STATED`; attach reproducible evidence.
6. Map callers, callees, state owners, persistence, interfaces, deployment, security, compatibility, and operations.
7. Record conventions for naming, layering, errors, logging, dependencies, tests, formatting, and public stability.

Expand the search boundary only when evidence points outside it.

## Map unknowns and blindspots

Classify:

- `KNOWN_KNOWNS`: verified facts.
- `KNOWN_UNKNOWNS`: explicit unanswered questions.
- `UNKNOWN_KNOWNS`: knowledge latent in code, tests, history, examples, screenshots, domain language, or human taste.
- `UNKNOWN_UNKNOWNS`: gaps exposed by systematic probes, counterexamples, failures, and affected consumers.

For each consequential unknown, record impact, current evidence, cheapest resolution, owner, and deadline phase. Probe every relevant blindspot category in the reference. Ask what could make the obvious approach wrong, which imported assumption lacks proof, which invariant could break, and what evidence would reverse the recommendation.

## Interview by blast radius

Investigate first. Ask the human only when evidence cannot resolve a consequential decision. Order questions from architecture, data, interface, security, and lifecycle decisions down to presentation.

Ask at most five numbered questions. Under each, state why it matters, evidence, uncertainty, and mutually exclusive options `A` through `D`. Put the recommended option first. Give a default only when it is safe and reversible.

If the human recognizes quality but lacks terminology, show compact contrasts, name the dimensions, and ask which result is recognizable. Do not demand jargon.

Challenge precise directions when repository or platform evidence contradicts them. State the conflict and consequence, recommend a correction, and ask for a decision. Refuse unsafe or unauthorized directions.

## Bound the loop

Run `Discover -> Hypothesize -> Inspect -> Verify -> Record -> Decide` only with a named question and new evidence target. Fingerprint question, evidence, and action. After three attempts with no uncertainty reduction or decision-relevant evidence, enter `AWAITING_HUMAN_INPUT`.

## Return evidence

Return the repository and execution map, evidence table, blast radius, four-part ledger, blindspot findings, conventions, human decisions, and phase 4 recommendation. Return control to `$mythos-orchestrate`; do not implement.

