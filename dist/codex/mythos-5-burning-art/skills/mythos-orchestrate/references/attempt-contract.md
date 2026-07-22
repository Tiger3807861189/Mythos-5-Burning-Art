# Durable implementation attempt contract

Read this contract before the first substantive phase-9 act and keep it active for build, debug, and repair. This is the single canonical attempt protocol; profile Skills add only profile-specific reasoning.

Every hook-authorized substantive tool invocation opens exactly one durable pending act. After that tool returns, perform only the read-only observation needed to capture its result, then emit exactly one packet before any other substantive tool, replan packet, waiting or terminal transition, or verification packet:

MYTHOS_ATTEMPT_PACKET_V1_BEGIN
```json
{
  "schema_version": 1,
  "run_id": "m5-...",
  "approval_bundle_hash": "<current approved bundle hash>",
  "step": "P-1",
  "hypothesis": "specific prediction tested",
  "action": "one bounded action performed",
  "evidence_snapshot": "new observation, including failed-tool evidence",
  "outcome": "PASS",
  "evidence_gain": true
}
```
MYTHOS_ATTEMPT_PACKET_V1_END

The `step` must name an approved plan step. `PASS` requires `evidence_gain: true`. A failed fingerprint may never repeat. The runtime binds the host-observed tool name, exact input hash, unique act ID, before-act fingerprint, and after-act project snapshot. The pending act survives restart. A second substantive tool, replan, wait, terminal transition, or verification request is denied until the packet closes the act; an unrecorded or out-of-scope content delta invalidates approval.

A host may emit `PermissionRequest` after `PreToolUse` for the same invocation. The runtime treats it as the second stage of the existing act only when the tool name, exact input hash, and host tool-use ID all match; it never opens a second act. A neutral hook ALLOW does not approve the tool: the host's native permission decision remains authoritative. If the human or native policy denies execution, close the existing act with `outcome: FAIL`, evidence that the tool did not run, the observed permission result, and truthful `evidence_gain`; do not pretend a mutation occurred.

After the third consecutive `FAIL` with `evidence_gain: false`, do not use another tool. Present the exact numbered A-D packet plus `MYTHOS_WAITING_FOR_HUMAN_V1`, or emit:

MYTHOS_TERMINAL_PACKET_V1_BEGIN
```json
{
  "schema_version": 1,
  "run_id": "m5-...",
  "terminal_state": "BLOCKED",
  "current_phase": "IMPLEMENTATION_LOOP",
  "reason": "specific blocking condition",
  "evidence": {"observation": "concrete nonempty evidence"},
  "resume_condition": "specific external change or human evidence required"
}
```
MYTHOS_TERMINAL_PACKET_V1_END

A model-emitted terminal packet may use only `BLOCKED` or `NEEDS_HUMAN_JUDGMENT`. Resume either only after the human sends `RESUME MYTHOS RUN <run-id>: <what changed>`. The runtime itself also records `AWAITING_HUMAN_PLAN_APPROVAL` and `VERIFICATION_FAILED` at their mandatory gates. An A-D waiting state resumes on the next human answer; when phase 9 was active it invalidates approval and requires phase-3 replanning.
