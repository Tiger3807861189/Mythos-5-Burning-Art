---
name: mythos-plan
description: "Convert discovered intent and evidence into exact acceptance criteria, a runtime-valid implementation plan, a sealed independent critique, and an explicit human approval gate. Use during Mythos phases 5 through 8 for build, debug, repair, and plan-only work."
---

# Mythos Plan

Read [references/plan-contract.md](references/plan-contract.md) completely before emitting a packet.

## Define acceptance before actions

Give every criterion a unique ID, an observable pass condition, and a verification method. Cover success, failure, regression, compatibility, security, performance, operations, and evidence when relevant. Replace vague criteria such as "works" or "robust" with observations. Trace every resolved unknown and selected option into a criterion or explicit non-goal.

Challenge a human method when repository evidence, platform constraints, safety, or the requested outcome contradict it. State evidence and consequence, recommend the better-supported method, and ask a numbered A-D question only when the difference is consequential.

## Produce only the protocol's fields

Each protocol plan step contains exactly `id`, `surfaces`, `action`, `verification`, and `rollback`.

Encode purpose, preconditions, dependencies, criteria covered, and the replan trigger precisely inside `action`; encode the immediate check and criterion IDs inside `verification`; encode reversal prerequisites inside `rollback`. Put baseline, repository dependencies, migration or rollout constraints, implementation-note obligations, and approval invalidators in the existing `intake`, `territory_discovery`, `unknowns`, `options`, and acceptance fields. Never invent extra JSON fields.

Order high-blast-radius or likely-to-change decisions before mechanical work. Name exact surfaces. A scope path ending in `/` or `\` authorizes that directory recursively; every other path authorizes only that exact path. Paths must be portable project-relative paths without `..`, drive prefixes, device namespaces, alternate streams, or reparse traversal. Use `external_effects: []`: this portable package never authorizes external-system effects. Use exact command strings only when required. Any nonempty command list causes approval, attempt, and verification snapshots to include common generated roots such as `node_modules`, `coverage`, `build`, and caches, because a command can change them even when no path explicitly names them. Every resulting changed file must still fall within approved path scope. Git metadata, permission-only, link, junction, and directory-only mutations are unsupported.

A non-mutating `debug` plan may use empty paths and empty step surfaces while listing exact diagnostic commands. A `plan_only` plan must use empty paths, commands, external effects, and step surfaces. Every other mutating plan requires paths and step surfaces.

## Seal and challenge independently

Emit one exact `MYTHOS_REVIEW_PACKET_V1` block. The Stop hook seals the original request, governing instructions, context manifest, replan provenance, planning material, and project fingerprint. Wait for its hash.

Then use the exact one-shot launch procedure in [the lifecycle contract](../mythos-orchestrate/references/lifecycle-contract.md). The observable launch intent, dedicated type, neutral prompt, new agent ID, nested transcript, and sealed hash must all bind; a SubagentStart identity alone is insufficient. If the hook cannot verify the chain, emit a terminal packet with `NEEDS_HUMAN_JUDGMENT` and reason `INDEPENDENT_REVIEW_UNAVAILABLE`. Never substitute same-context criticism.

A critic PASS must cover exactly these twelve sealed sections once:

`task_profile`, `replan_provenance`, `original_request`, `context_manifest`, `goal`, `intake`, `territory_discovery`, `unknowns`, `options`, `acceptance_criteria`, `plan`, `mutation_scope`.

It must return exactly one `Verdict: PASS` and one strict receipt bound to the hook hash, with empty blocking, high, and contamination arrays. Any revision requires a new packet, `replan_from: "UNKNOWNS_AND_BLINDSPOTS"`, and a different fresh critic.

## Stop for human approval

After a bound PASS, present the final plan and emit `MYTHOS_APPROVAL_BUNDLE_V1` using the unchanged planning fields, exact review hash, and critic adjudication. Stop. Accept only the exact approval statement produced by the hook. Initial intent, silence, urgency, tool permission, or an old approval is not approval of this plan.

Return control to `$mythos-orchestrate`; never code in this skill.
