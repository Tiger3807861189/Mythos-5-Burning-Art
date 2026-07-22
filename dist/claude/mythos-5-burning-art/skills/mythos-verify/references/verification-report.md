# Verification Report and Packet Contract

## Submitted verification packet

The submitter supplies only these fields. Each reconciliation entry binds to a concrete subject. Include one `PLAN_STEP` entry for every approved step and one `PATH` entry for every changed path that the hook will observe. `ACCEPTANCE_CRITERION` and `COMMAND` entries are optional when useful.

MYTHOS_VERIFICATION_PACKET_V1_BEGIN
```json
{
  "schema_version": 1,
  "run_id": "m5-...",
  "approval_bundle_hash": "<current approved bundle hash>",
  "implementation_notes": {"summary":"...","changed_surfaces":["..."]},
  "increment_evidence": [
    {"step":"P-1","observation":"specific observed result","result":"PASS"}
  ],
  "acceptance_evidence": [
    {"criterion":"AC-1","evidence":"specific direct evidence","result":"PASS"}
  ],
  "reconciliation": {
    "deviations": [
      {"subject_type":"PLAN_STEP","subject_id":"P-1","classification":"MATCH","evidence":"..."},
      {"subject_type":"PATH","subject_id":"src/exact-file.py","classification":"MATCH","evidence":"..."}
    ]
  }
}
```
MYTHOS_VERIFICATION_PACKET_V1_END

For `plan_only`, `increment_evidence` is `[]`, paths and content delta are empty, and reconciliation still covers every plan step. For a non-mutating debug plan, durable diagnostic attempts and increment evidence remain required, but the changed-path list is empty.

The hook adds `final_scope`, `final_fingerprint`, manifest hashes, `changed_inventory`, and exact `content_delta`. Never submit or guess those hook-owned fields.

## Fresh verifier receipt

Start only after the hook returns the packet hash, with host-observable no-inherited-turn isolation.

```text
Verdict: PASS
MYTHOS_VERIFIER_RECEIPT_V1_BEGIN
{"schema_version":1,"packet_hash":"<verification_packet_hash>","verdict":"PASS","criteria":[{"criterion":"AC-1","result":"PASS","evidence":"direct verifier evidence"}],"scope_matches_approval":true,"approval_current":true,"blocking_findings":[],"high_findings":[],"context_contamination":[]}
MYTHOS_VERIFIER_RECEIPT_V1_END
```

Multiple verdicts or receipts, a mismatched hash, duplicate or missing criteria, a non-PASS criterion, false scope/approval flags, or any blocking/high/contamination item invalidates PASS.

## Completion bundle

After the bound PASS, copy the submitted verification material exactly and add only the hook-owned verification hash and explanation. Reconciliation still contains only submitted deviations.

MYTHOS_COMPLETION_BUNDLE_V1_BEGIN
```json
{
  "schema_version": 1,
  "run_id": "m5-...",
  "verification_packet_hash": "<verification_packet_hash>",
  "implementation_notes": {"summary":"...","changed_surfaces":["..."]},
  "increment_evidence": [
    {"step":"P-1","observation":"specific observed result","result":"PASS"}
  ],
  "acceptance_evidence": [
    {"criterion":"AC-1","evidence":"specific direct evidence","result":"PASS"}
  ],
  "reconciliation": {
    "deviations": [
      {"subject_type":"PLAN_STEP","subject_id":"P-1","classification":"MATCH","evidence":"..."},
      {"subject_type":"PATH","subject_id":"src/exact-file.py","classification":"MATCH","evidence":"..."}
    ]
  },
  "explanation": {
    "change_explanation": "...",
    "risks": ["..."],
    "rollback": "...",
    "comprehension_evidence": "human response, explicit waiver, or evidenced low-impact waiver"
  }
}
```
MYTHOS_COMPLETION_BUNDLE_V1_END

The hook checks byte-for-byte semantic identity with the submitted packet, fresh verifier binding, approval currency, current global and scoped fingerprints, content delta, manifests, changed inventory, criterion coverage, and all phase evidence before DONE. Any change after sealing requires a new review and approval; the frozen snapshot is never reopened under the old approval.
