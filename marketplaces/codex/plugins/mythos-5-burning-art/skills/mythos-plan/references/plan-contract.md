# Plan Contract

## Exact planning schema

The runtime accepts no undocumented fields. A criterion is exactly:

```json
{"id":"AC-1","pass_condition":"observable condition","verification":"specific check"}
```

A plan step is exactly:

```json
{"id":"P-1","surfaces":["src/exact-file.py"],"action":"Purpose, preconditions, dependencies, criteria covered, bounded action, and replan trigger.","verification":"Immediate check and criterion IDs.","rollback":"Exact reversal and prerequisites."}
```

A trailing slash makes a path recursive: `src/module/` covers descendants; `src/module` covers only that exact path. Use project-relative portable paths only. `external_effects` is always `[]`. The portable runtime does not support external effects, Git metadata mutations, permission-only changes, symlink/hardlink/junction creation, or directory-only mutations.

For a non-mutating debug plan, use empty `paths` and empty step `surfaces`; exact diagnostic `commands` may remain. For `plan_only`, paths, commands, external effects, and surfaces are all empty.

## Review packet

Use the run ID supplied by SessionStart. An initial packet omits `replan_from`; every later packet includes `"replan_from":"UNKNOWNS_AND_BLINDSPOTS"`.

MYTHOS_REVIEW_PACKET_V1_BEGIN
```json
{
  "schema_version": 1,
  "run_id": "m5-...",
  "task_profile": "build",
  "goal": "Observable outcome",
  "intake": {
    "outcome": "...",
    "scope": "...",
    "constraints": ["..."],
    "non_goals": ["..."],
    "authorization": "planning only before approval"
  },
  "territory_discovery": {
    "repository_map": ["..."],
    "instructions": ["AGENTS.md or none observed"],
    "conventions": ["..."],
    "baseline": "..."
  },
  "unknowns": {
    "known_knowns": ["..."],
    "known_unknowns": ["..."],
    "unknown_knowns": ["..."],
    "unknown_unknowns": ["..."],
    "blindspot_pass": ["..."]
  },
  "options": {"status":"PASS","disposition":"Selected direction and rejected alternatives"},
  "acceptance_criteria": [
    {"id":"AC-1","pass_condition":"...","verification":"..."}
  ],
  "plan": [
    {"id":"P-1","surfaces":["src/exact-file.py"],"action":"...","verification":"...","rollback":"..."}
  ],
  "mutation_scope": {
    "paths": ["src/exact-file.py", "tests/unit/"],
    "commands": ["python -B -m unittest tests.unit.test_feature"],
    "external_effects": []
  }
}
```
MYTHOS_REVIEW_PACKET_V1_END

Phase 4 `NOT_APPLICABLE` uses only a runtime-permitted code and exact evidence keys. Use `single_mechanical_outcome` with `only_viable_change` and `risk_assessment`, or `no_safe_executable_prototype` with `prototype_risk` and `non_mutating_alternative`. The portable package has no preapproval executable prototype runner; use non-mutating references or record the justified N/A result.

## Critic receipt

Launch only after the hook returns the sealed hash, and require host-observable fresh isolation.

```text
Verdict: PASS
MYTHOS_CRITIC_RECEIPT_V1_BEGIN
{"schema_version":1,"packet_hash":"<review_packet_hash>","verdict":"PASS","reviewed_sections":["task_profile","replan_provenance","original_request","context_manifest","goal","intake","territory_discovery","unknowns","options","acceptance_criteria","plan","mutation_scope"],"blocking_findings":[],"high_findings":[],"context_contamination":[]}
MYTHOS_CRITIC_RECEIPT_V1_END
```

## Approval bundle

Copy the planning fields without semantic change, then add only:

```json
{
  "review_packet_hash": "<review_packet_hash>",
  "critic": {
    "adjudication": [
      {"finding":"C-1 or none","disposition":"ACCEPT","evidence":"specific evidence"}
    ]
  }
}
```

Place those keys in the full planning object and wrap it with `MYTHOS_APPROVAL_BUNDLE_V1_BEGIN` and `MYTHOS_APPROVAL_BUNDLE_V1_END`. The hook returns the only valid statement:

```text
APPROVE MYTHOS RUN <run-id> BUNDLE <bundle-hash>
```

Stop and wait for a new human message containing that exact statement.
