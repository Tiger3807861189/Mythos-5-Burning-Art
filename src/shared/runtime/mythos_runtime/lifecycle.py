"""The mandatory thirteen-phase lifecycle and transition policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Phase(str, Enum):
    INTAKE = "INTAKE"
    TERRITORY_DISCOVERY = "TERRITORY_DISCOVERY"
    UNKNOWNS_AND_BLINDSPOTS = "UNKNOWNS_AND_BLINDSPOTS"
    OPTIONS_REFERENCES_OR_PROTOTYPES = "OPTIONS_REFERENCES_OR_PROTOTYPES"
    ACCEPTANCE_CRITERIA = "ACCEPTANCE_CRITERIA"
    IMPLEMENTATION_PLAN = "IMPLEMENTATION_PLAN"
    INDEPENDENT_PLAN_CRITIQUE = "INDEPENDENT_PLAN_CRITIQUE"
    AWAITING_HUMAN_PLAN_APPROVAL = "AWAITING_HUMAN_PLAN_APPROVAL"
    IMPLEMENTATION_LOOP = "IMPLEMENTATION_LOOP"
    INDEPENDENT_VERIFICATION = "INDEPENDENT_VERIFICATION"
    PLAN_VS_ACTUAL_RECONCILIATION = "PLAN_VS_ACTUAL_RECONCILIATION"
    EXPLANATION_AND_COMPREHENSION_CHECK = "EXPLANATION_AND_COMPREHENSION_CHECK"
    DONE = "DONE"


PHASES = tuple(Phase)


class PhaseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class TerminalState(str, Enum):
    DONE = "DONE"
    BLOCKED = "BLOCKED"
    NEEDS_HUMAN_JUDGMENT = "NEEDS_HUMAN_JUDGMENT"
    AWAITING_HUMAN_INPUT = "AWAITING_HUMAN_INPUT"
    AWAITING_HUMAN_PLAN_APPROVAL = "AWAITING_HUMAN_PLAN_APPROVAL"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


class LifecycleError(ValueError):
    pass


LINEAR_NEXT = {current: following for current, following in zip(PHASES, PHASES[1:])}
BACK_EDGES = {
    Phase.AWAITING_HUMAN_PLAN_APPROVAL: {Phase.UNKNOWNS_AND_BLINDSPOTS},
    Phase.IMPLEMENTATION_LOOP: {Phase.UNKNOWNS_AND_BLINDSPOTS},
    Phase.INDEPENDENT_VERIFICATION: {Phase.UNKNOWNS_AND_BLINDSPOTS},
}


@dataclass(frozen=True)
class NotApplicableRule:
    profiles: frozenset[str]
    required_evidence_keys: frozenset[str]


NOT_APPLICABLE_RULES = {
    Phase.OPTIONS_REFERENCES_OR_PROTOTYPES: {
        "single_mechanical_outcome": NotApplicableRule(
            profiles=frozenset({"build", "debug", "repair"}),
            required_evidence_keys=frozenset({"only_viable_change", "risk_assessment"}),
        ),
        "no_safe_executable_prototype": NotApplicableRule(
            profiles=frozenset({"build", "debug", "repair", "plan_only"}),
            required_evidence_keys=frozenset({"prototype_risk", "non_mutating_alternative"}),
        ),
    },
    Phase.IMPLEMENTATION_LOOP: {
        "plan_only_no_mutation": NotApplicableRule(
            profiles=frozenset({"plan_only"}),
            required_evidence_keys=frozenset({"approved_plan", "no_mutation_performed"}),
        ),
    },
}


def validate_not_applicable(
    *,
    phase: Phase,
    profile: str,
    code: str | None,
    reason: str | None,
    evidence: dict[str, Any] | None,
) -> None:
    if not code or not reason or not reason.strip():
        raise LifecycleError("NOT_APPLICABLE requires a policy code and a specific reason")
    rule = NOT_APPLICABLE_RULES.get(phase, {}).get(code)
    if not rule:
        raise LifecycleError(f"NOT_APPLICABLE is not permitted for {phase.value} with code {code!r}")
    if profile not in rule.profiles:
        raise LifecycleError(f"NOT_APPLICABLE code {code!r} is not permitted for profile {profile!r}")
    evidence = evidence or {}
    missing = sorted(rule.required_evidence_keys.difference(evidence))
    if missing:
        raise LifecycleError(f"NOT_APPLICABLE evidence is missing: {', '.join(missing)}")
    extras = sorted(set(evidence).difference(rule.required_evidence_keys))
    if extras:
        raise LifecycleError("NOT_APPLICABLE evidence contains unsupported keys: " + ", ".join(extras))
    if any(not isinstance(evidence[key], str) or not evidence[key].strip() for key in rule.required_evidence_keys):
        raise LifecycleError("NOT_APPLICABLE evidence values must be non-empty strings")


def validate_transition(current: Phase, target: Phase, *, approval_valid: bool) -> None:
    allowed = {LINEAR_NEXT[current]} if current in LINEAR_NEXT else set()
    allowed.update(BACK_EDGES.get(current, set()))
    if target not in allowed:
        raise LifecycleError(f"Illegal lifecycle transition: {current.value} -> {target.value}")
    if target is Phase.IMPLEMENTATION_LOOP and current is Phase.AWAITING_HUMAN_PLAN_APPROVAL:
        if not approval_valid:
            raise LifecycleError("Implementation cannot start without a current hook-owned approval")


def default_phase_statuses() -> dict[str, str]:
    statuses = {phase.value: PhaseStatus.PENDING.value for phase in PHASES}
    statuses[Phase.INTAKE.value] = PhaseStatus.ACTIVE.value
    return statuses


