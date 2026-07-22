"""Run state, lifecycle transitions, evidence, and loop stopping rules."""

from __future__ import annotations

import copy
import os
import uuid
from pathlib import Path
from typing import Any, Callable

from .canonical import digest, project_identity
from .lifecycle import (
    PHASES,
    LifecycleError,
    Phase,
    PhaseStatus,
    TerminalState,
    default_phase_statuses,
    validate_not_applicable,
    validate_transition,
)
from .locking import FileLock
from .paths import prepare_private_directory, run_paths, user_state_root
from .storage import EventLog, IntegrityError, atomic_write_json, read_json


class StateError(RuntimeError):
    pass


class SessionMismatch(StateError):
    pass


def attempt_fingerprint(
    *,
    phase: str,
    approval_bundle_hash: str,
    step: str,
    hypothesis: Any,
    action: Any,
    evidence_snapshot: Any,
    project_fingerprint: str,
) -> str:
    return digest({
        "phase": phase,
        "approval_bundle_hash": approval_bundle_hash,
        "step": step,
        "hypothesis": hypothesis,
        "action": action,
        "evidence_snapshot": evidence_snapshot,
        "project_fingerprint": project_fingerprint,
    })
def _initial_state(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "run_id": payload["run_id"],
        "session_id": payload["session_id"],
        "project": payload["project"],
        "task_profile": payload["task_profile"],
        "phase": Phase.INTAKE.value,
        "phase_statuses": default_phase_statuses(),
        "phase_records": [],
        "evidence": {},
        "attempts": [],
        "repeated_no_gain_failures": 0,
        "must_stop": False,
        "terminal_state": None,
        "terminal_reason": None,
        "terminal_evidence": None,
        "resume_condition": None,
        "last_sequence": 0,
    }


def _apply_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    operation = event.get("operation")
    if operation == "batch":
        events = event.get("events")
        if not isinstance(events, list) or not events:
            raise IntegrityError("A batch event must contain a non-empty event array")
        for nested in events:
            if not isinstance(nested, dict) or nested.get("operation") in {"initialize", "batch"}:
                raise IntegrityError("A batch may contain only non-batch, non-initialize events")
            state = _apply_event(state, nested)
        return state
    if operation == "transition":
        current = event["from_phase"]
        target = event["to_phase"]
        state["phase_statuses"][current] = event["outcome"]
        state["phase_statuses"][target] = (
            PhaseStatus.PASS.value if target == Phase.DONE.value else PhaseStatus.ACTIVE.value
        )
        state["phase"] = target
        if target == Phase.IMPLEMENTATION_LOOP.value:
            state["repeated_no_gain_failures"] = 0
            state["must_stop"] = False
        state["phase_records"].append(
            {
                "phase": current,
                "outcome": event["outcome"],
                "reason": event.get("reason"),
                "evidence": event.get("evidence", {}),
                "not_applicable_code": event.get("not_applicable_code"),
            }
        )
        if target == Phase.DONE.value:
            state["terminal_state"] = TerminalState.DONE.value
            state["terminal_reason"] = None
            state["terminal_evidence"] = None
            state["resume_condition"] = None
    elif operation == "set_task_profile":
        if state["phase"] != Phase.INTAKE.value or state["phase_records"]:
            raise IntegrityError("Task profile may change only during initial intake")
        state["task_profile"] = event["task_profile"]
    elif operation == "record_evidence":
        state["evidence"][event["kind"]] = event["value"]
    elif operation == "attempt":
        state["attempts"].append({key: value for key, value in event.items() if key != "operation"})
        pending = state.get("evidence", {}).get("pending_attempt", {})
        state["evidence"]["pending_attempt"] = {
            "active": False,
            "approval_bundle_hash": event["approval_bundle_hash"],
            "act_id": event["act_id"],
            "tool_name": event["tool_name"],
            "tool_input_hash": event["tool_input_hash"],
            "tool_use_id": pending.get("tool_use_id"),
            "permission_request_observed": pending.get("permission_request_observed", False),
            "permission_request_count": pending.get("permission_request_count", 0),
            "project_fingerprint_before": event["project_fingerprint_before"],
            "resolved_by_fingerprint": event["fingerprint"],
            "began_from": pending.get("began_from", "PreToolUse"),
        }
        if event["failed"] and not event["evidence_gain"]:
            state["repeated_no_gain_failures"] += 1
        else:
            state["repeated_no_gain_failures"] = 0
        state["must_stop"] = state["repeated_no_gain_failures"] >= 3
    elif operation == "set_terminal":
        state["terminal_state"] = event["terminal_state"]
        state["terminal_reason"] = event["reason"]
        state["terminal_evidence"] = event.get("evidence", {})
        state["resume_condition"] = event.get("resume_condition")
        state["phase_statuses"][state["phase"]] = PhaseStatus.BLOCKED.value
    elif operation == "resume":
        state["terminal_state"] = None
        state["terminal_reason"] = None
        state["terminal_evidence"] = None
        state["resume_condition"] = None
        state["phase_statuses"][state["phase"]] = PhaseStatus.ACTIVE.value
        state["must_stop"] = False
        state["repeated_no_gain_failures"] = 0
    else:
        raise IntegrityError(f"Unknown run operation: {operation!r}")
    return state


def reduce_events(records: list[dict[str, Any]]) -> dict[str, Any]:
    state: dict[str, Any] | None = None
    for record in records:
        event = record["payload"]
        if event.get("operation") == "initialize":
            if state is not None:
                raise IntegrityError("Run contains multiple initialize events")
            state = _initial_state(event)
        elif state is None:
            raise IntegrityError("The first run event must initialize the run")
        else:
            state = _apply_event(state, event)
        state["last_sequence"] = record["sequence"]
    if state is None:
        raise StateError("Run has not been initialized")
    return state

class RuntimeStore:
    """Transactional run state stored outside the project by default."""

    def __init__(
        self,
        project_root: str | os.PathLike[str],
        run_id: str,
        *,
        root: str | os.PathLike[str] | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve(strict=False)
        self.identity = project_identity(self.project_root)
        self.run_id = run_id
        if not run_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in run_id):
            raise ValueError("run_id may contain only letters, digits, hyphens, and underscores")
        self.root = Path(root) if root else user_state_root()
        self.paths = run_paths(
            self.root,
            str(self.identity["repository_id"]),
            str(self.identity["worktree_id"]),
            run_id,
        )
        prepare_private_directory(self.paths["agent"])
        self.log = EventLog(self.paths["events"])

    def initialize(self, *, session_id: str, task_profile: str) -> dict[str, Any]:
        if task_profile not in {"build", "debug", "repair", "plan_only"}:
            raise ValueError("task_profile must be build, debug, repair, or plan_only")
        payload = {
            "operation": "initialize",
            "run_id": self.run_id,
            "session_id": session_id,
            "project": self.identity,
            "task_profile": task_profile,
        }
        with FileLock(self.paths["run_lock"]):
            records = self.log.read_verified()
            if records:
                state = reduce_events(records)
                self._require_session(state, session_id)
                atomic_write_json(self.paths["snapshot"], state)
                return state
            self.log.append(payload)
            state = self._load_unlocked()
            atomic_write_json(self.paths["snapshot"], state)
            return state
    def _require_session(self, state: dict[str, Any], session_id: str) -> None:
        if state.get("project") != self.identity:
            raise StateError("Run state belongs to a different repository or worktree identity")
        if state["session_id"] != session_id:
            raise SessionMismatch(
                f"Run {self.run_id} is bound to session {state['session_id']!r}, not {session_id!r}"
            )

    def _load_unlocked(self) -> dict[str, Any]:
        records = self.log.read_verified()
        return reduce_events(records)

    def load(self) -> dict[str, Any]:
        with FileLock(self.paths["run_lock"]):
            state = self._load_unlocked()
            if state.get("project") != self.identity:
                raise StateError("Run state belongs to a different repository or worktree identity")
            if self.paths["snapshot"].exists():
                snapshot = read_json(self.paths["snapshot"])
                if snapshot != state:
                    raise IntegrityError("Atomic snapshot does not match the append-only event log")
            return state

    def rebuild_snapshot(self) -> dict[str, Any]:
        with FileLock(self.paths["run_lock"]):
            state = self._load_unlocked()
            atomic_write_json(self.paths["snapshot"], state)
            return state

    def _mutate(
        self,
        session_id: str | None,
        build_event: Callable[[dict[str, Any] | None], dict[str, Any]],
    ) -> dict[str, Any]:
        with FileLock(self.paths["run_lock"]):
            records = self.log.read_verified()
            current = reduce_events(records) if records else None
            if current is not None and session_id is not None:
                self._require_session(current, session_id)
            event = build_event(copy.deepcopy(current))
            self.log.append(event)
            state = self._load_unlocked()
            atomic_write_json(self.paths["snapshot"], state)
            return state

    def transition(
        self,
        *,
        session_id: str,
        to_phase: Phase | str,
        outcome: PhaseStatus | str = PhaseStatus.PASS,
        approval_valid: bool = False,
        reason: str | None = None,
        evidence: dict[str, Any] | None = None,
        not_applicable_code: str | None = None,
    ) -> dict[str, Any]:
        target = Phase(to_phase)
        result = PhaseStatus(outcome)
        if result not in {PhaseStatus.PASS, PhaseStatus.NOT_APPLICABLE}:
            raise LifecycleError("A transition must complete the current phase as PASS or NOT_APPLICABLE")

        def build(state: dict[str, Any] | None) -> dict[str, Any]:
            if state is None:
                raise StateError("Run has not been initialized")
            if state["terminal_state"] is not None:
                raise LifecycleError("A terminal or waiting run must be resumed before transition")
            current = Phase(state["phase"])
            validate_transition(current, target, approval_valid=approval_valid)
            if result is PhaseStatus.NOT_APPLICABLE:
                validate_not_applicable(
                    phase=current,
                    profile=state["task_profile"],
                    code=not_applicable_code,
                    reason=reason,
                    evidence=evidence,
                )
            if target is Phase.DONE:
                failures = done_guard_failures(state, completing_phase=current)
                if failures:
                    raise LifecycleError("DONE guard failed: " + "; ".join(failures))
            return {
                "operation": "transition",
                "from_phase": current.value,
                "to_phase": target.value,
                "outcome": result.value,
                "reason": reason,
                "evidence": evidence or {},
                "not_applicable_code": not_applicable_code,
            }

        return self._mutate(session_id, build)

    def apply_batch(self, *, session_id: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
        """Validate and append a hook workflow as one crash-safe log record."""

        if not isinstance(operations, list) or not operations:
            raise ValueError("A runtime batch requires a non-empty operation list")

        def build(state: dict[str, Any] | None) -> dict[str, Any]:
            if state is None:
                raise StateError("Run has not been initialized")
            simulated = copy.deepcopy(state)
            normalized: list[dict[str, Any]] = []
            for requested in operations:
                if not isinstance(requested, dict):
                    raise ValueError("Every batch operation must be an object")
                operation = requested.get("operation")
                if operation == "record_evidence":
                    kind = requested.get("kind")
                    value = requested.get("value")
                    if not isinstance(kind, str) or not kind.strip() or value in (None, "", [], {}):
                        raise ValueError("Batch evidence kind and value must be non-empty")
                    event = {"operation": "record_evidence", "kind": kind, "value": value}
                elif operation == "transition":
                    if simulated["terminal_state"] is not None:
                        raise LifecycleError("A terminal or waiting run must be resumed before transition")
                    current = Phase(simulated["phase"])
                    target = Phase(requested["to_phase"])
                    result = PhaseStatus(requested.get("outcome", PhaseStatus.PASS.value))
                    if result not in {PhaseStatus.PASS, PhaseStatus.NOT_APPLICABLE}:
                        raise LifecycleError("A transition must complete the current phase as PASS or NOT_APPLICABLE")
                    validate_transition(current, target, approval_valid=bool(requested.get("approval_valid", False)))
                    reason = requested.get("reason")
                    evidence = requested.get("evidence") or {}
                    code = requested.get("not_applicable_code")
                    if result is PhaseStatus.NOT_APPLICABLE:
                        validate_not_applicable(
                            phase=current,
                            profile=simulated["task_profile"],
                            code=code,
                            reason=reason,
                            evidence=evidence,
                        )
                    if target is Phase.DONE:
                        failures = done_guard_failures(simulated, completing_phase=current)
                        if failures:
                            raise LifecycleError("DONE guard failed: " + "; ".join(failures))
                    event = {
                        "operation": "transition",
                        "from_phase": current.value,
                        "to_phase": target.value,
                        "outcome": result.value,
                        "reason": reason,
                        "evidence": evidence,
                        "not_applicable_code": code,
                    }
                else:
                    raise ValueError(f"Unsupported batch operation: {operation!r}")
                normalized.append(event)
                simulated = _apply_event(simulated, event)
            return {"operation": "batch", "events": normalized}

        return self._mutate(session_id, build)
    def set_task_profile(self, *, session_id: str, task_profile: str) -> dict[str, Any]:
        if task_profile not in {"build", "debug", "repair", "plan_only"}:
            raise ValueError("task_profile must be build, debug, repair, or plan_only")

        def build(state: dict[str, Any] | None) -> dict[str, Any]:
            if state is None:
                raise StateError("Run has not been initialized")
            if state["phase"] != Phase.INTAKE.value or state["phase_records"]:
                raise LifecycleError("Task profile may change only during initial intake")
            return {"operation": "set_task_profile", "task_profile": task_profile}

        return self._mutate(session_id, build)

    def record_evidence(self, *, session_id: str, kind: str, value: Any) -> dict[str, Any]:
        if not kind.strip() or value in (None, "", [], {}):
            raise ValueError("Evidence kind and value must be non-empty")
        return self._mutate(
            session_id,
            lambda state: {"operation": "record_evidence", "kind": kind, "value": value},
        )

    def begin_act(
        self,
        *,
        session_id: str,
        approval_bundle_hash: str,
        tool_name: str,
        tool_input_hash: str,
        tool_use_id: str | None = None,
        project_fingerprint_before: str,
    ) -> dict[str, Any]:
        """Atomically reserve one substantive act until its attempt packet arrives."""

        for label, value, length in (
            ("approval_bundle_hash", approval_bundle_hash, 64),
            ("tool_input_hash", tool_input_hash, 64),
            ("project_fingerprint_before", project_fingerprint_before, 64),
        ):
            if not isinstance(value, str) or len(value) != length or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{label} must be a lowercase SHA-256 digest")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError("tool_name must be a non-empty string")
        if tool_use_id is not None and (not isinstance(tool_use_id, str) or not tool_use_id.strip()):
            raise ValueError("tool_use_id must be a non-empty string when supplied")

        def build(state: dict[str, Any] | None) -> dict[str, Any]:
            if state is None:
                raise StateError("Run has not been initialized")
            if state["phase"] != Phase.IMPLEMENTATION_LOOP.value or state.get("terminal_state") is not None:
                raise LifecycleError("A substantive act may begin only during an active IMPLEMENTATION_LOOP")
            if state.get("must_stop"):
                raise LifecycleError("The implementation loop is stopped")
            if state.get("task_profile") == "plan_only":
                raise LifecycleError("A plan_only run cannot begin an implementation act")
            if state.get("evidence", {}).get("pending_verification_packet", {}).get("active") is True:
                raise LifecycleError("A frozen verification snapshot forbids new acts")
            pending = state.get("evidence", {}).get("pending_attempt", {})
            if pending.get("active") is True:
                raise LifecycleError("The prior substantive act requires an exact attempt packet before another act")
            return {
                "operation": "record_evidence",
                "kind": "pending_attempt",
                "value": {
                    "active": True,
                    "approval_bundle_hash": approval_bundle_hash,
                    "act_id": uuid.uuid4().hex,
                    "tool_name": tool_name,
                    "tool_input_hash": tool_input_hash,
                    "tool_use_id": tool_use_id,
                    "permission_request_observed": False,
                    "permission_request_count": 0,
                    "project_fingerprint_before": project_fingerprint_before,
                    "began_from": "PreToolUse",
                },
            }

        return self._mutate(session_id, build)

    def record_attempt(
        self,
        *,
        session_id: str,
        approval_bundle_hash: str,
        step: str,
        hypothesis: Any,
        action: Any,
        evidence_snapshot: Any,
        project_fingerprint: str,
        authority_valid_at_close: bool,
        authority_invalid_reasons: list[str],
        scope_valid_at_close: bool,
        unapproved_paths: list[str],
        failed: bool,
        evidence_gain: bool,
    ) -> dict[str, Any]:
        def build(state: dict[str, Any] | None) -> dict[str, Any]:
            if state is None:
                raise StateError("Run has not been initialized")
            pending = state.get("evidence", {}).get("pending_attempt", {})
            if pending.get("active") is not True:
                raise LifecycleError("Every attempt packet must close one pending substantive act")
            if pending.get("approval_bundle_hash") != approval_bundle_hash:
                raise LifecycleError("The pending act belongs to another approval bundle")
            fingerprint = attempt_fingerprint(
                phase=state["phase"],
                approval_bundle_hash=approval_bundle_hash,
                step=step,
                hypothesis=hypothesis,
                action=action,
                evidence_snapshot=evidence_snapshot,
                project_fingerprint=project_fingerprint,
            )
            if failed and any(
                item.get("failed") and item.get("fingerprint") == fingerprint
                for item in state["attempts"]
            ):
                raise LifecycleError("A failed attempt fingerprint must not be repeated; change the hypothesis, action, or evidence")
            return {
                "operation": "attempt",
                "fingerprint": fingerprint,
                "phase": state["phase"],
                "approval_bundle_hash": approval_bundle_hash,
                "act_id": pending["act_id"],
                "tool_name": pending["tool_name"],
                "tool_input_hash": pending["tool_input_hash"],
                "tool_use_id": pending.get("tool_use_id"),
                "permission_request_observed": pending.get("permission_request_observed", False),
                "permission_request_count": pending.get("permission_request_count", 0),
                "project_fingerprint_before": pending["project_fingerprint_before"],
                "authority_valid_at_close": bool(authority_valid_at_close),
                "authority_invalid_reasons": list(authority_invalid_reasons),
                "scope_valid_at_close": bool(scope_valid_at_close),
                "unapproved_paths": list(unapproved_paths),
                "step": step,
                "hypothesis": hypothesis,
                "action": action,
                "evidence_snapshot": evidence_snapshot,
                "project_fingerprint": project_fingerprint,
                "failed": bool(failed),
                "evidence_gain": bool(evidence_gain),
            }

        return self._mutate(session_id, build)
    def set_terminal(
        self,
        *,
        session_id: str,
        terminal_state: TerminalState | str,
        reason: str,
        evidence: dict[str, Any] | None = None,
        resume_condition: str | None = None,
    ) -> dict[str, Any]:
        selected = TerminalState(terminal_state)
        if selected is TerminalState.DONE:
            raise LifecycleError("DONE may be entered only through the guarded phase transition")
        if not reason.strip():
            raise ValueError("A terminal or waiting state requires a reason")
        if evidence is not None and not isinstance(evidence, dict):
            raise ValueError("Terminal evidence must be an object")
        if resume_condition is not None and not resume_condition.strip():
            raise ValueError("resume_condition must be a non-empty string when supplied")
        def build(state: dict[str, Any] | None) -> dict[str, Any]:
            if state is None:
                raise StateError("Run has not been initialized")
            if state["phase"] == Phase.DONE.value or state["terminal_state"] is not None:
                raise LifecycleError("A terminal state cannot overwrite DONE or another terminal state")
            if state.get("evidence", {}).get("pending_attempt", {}).get("active") is True:
                raise LifecycleError("Close the pending substantive act with an exact attempt packet before entering a terminal state")
            return {
                "operation": "set_terminal",
                "terminal_state": selected.value,
                "reason": reason,
                "evidence": evidence or {},
                "resume_condition": resume_condition,
            }

        return self._mutate(session_id, build)

    def resume(self, *, session_id: str) -> dict[str, Any]:
        def build(state: dict[str, Any] | None) -> dict[str, Any]:
            if state is None or state["terminal_state"] not in {
                TerminalState.AWAITING_HUMAN_INPUT.value,
                TerminalState.AWAITING_HUMAN_PLAN_APPROVAL.value,
                TerminalState.NEEDS_HUMAN_JUDGMENT.value,
                TerminalState.BLOCKED.value,
                TerminalState.VERIFICATION_FAILED.value,
            }:
                raise LifecycleError("Only a human-waiting run can be resumed")
            return {"operation": "resume"}

        return self._mutate(session_id, build)


def done_guard_failures(state: dict[str, Any], *, completing_phase: Phase | None = None) -> list[str]:
    failures: list[str] = []
    required_evidence = {
        "acceptance_evidence",
        "independent_verification",
        "plan_vs_actual_reconciliation",
        "implementation_notes",
        "explanation_and_comprehension",
    }
    missing = sorted(required_evidence.difference(state.get("evidence", {})))
    if missing:
        failures.append("missing evidence: " + ", ".join(missing))
    for phase in PHASES[:-1]:
        status = state.get("phase_statuses", {}).get(phase.value)
        if phase is completing_phase and status == PhaseStatus.ACTIVE.value:
            continue
        if status not in {PhaseStatus.PASS.value, PhaseStatus.NOT_APPLICABLE.value}:
            failures.append(f"phase {phase.value} is {status or 'UNRECORDED'}")
    if state.get("must_stop"):
        failures.append("the repeated-attempt stopping rule is active")
    if state.get("evidence", {}).get("pending_attempt", {}).get("active") is True:
        failures.append("a substantive act still lacks its exact attempt packet")
    if state.get("terminal_state") not in {None, TerminalState.DONE.value}:
        failures.append(f"terminal state is already {state['terminal_state']}")
    return failures

