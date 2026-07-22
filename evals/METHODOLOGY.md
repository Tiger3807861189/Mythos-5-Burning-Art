# Behavioral Contract Fixture Methodology

## Purpose

This is a deterministic prompt-contract regression fixture. It is not a live model benchmark, not a repository execution benchmark, and not a claim that a weaker model equals Fable 5 or Mythos 5. It checks that representative responses preserve the orchestration contract under stipulated facts.

## Fixture isolation

Each scenario supplies only its own stipulated facts. Each stored response is maintained as a static release fixture against:

1. `src/shared/skills/mythos-orchestrate/SKILL.md`;
2. `src/shared/skills/mythos-orchestrate/references/lifecycle-contract.md`;
3. the corresponding scenario file.

The fixtures must not claim repository observations that a scenario does not supply. They may require later discovery, ask a consequential exact A-D question, or enter an explicit non-success state. They do not mutate files or invoke agents.

## Grading

`scripts/verify_evals.py` deterministically grades every UTF-8 response, verifies scenario and response hashes, binds the current orchestration skill and lifecycle contract, rejects duplicate fixture identifiers, and recomputes the summary. The archived `grader_trace` is supplemental human-readable provenance.

The response text is a maintained expected-behavior artifact, not evidence that a named model produced the response in a live run. Run `python -B scripts/verify_evals.py` to reproduce the audit.

## Limits

These fixtures test visible protocol behavior only. Runtime enforcement, host integration, state durability, concurrency, mutation scope, and fresh-context isolation are covered by the executable contract tests. No exact backend model build or public run UUID applies to a static fixture.