"""Host-neutral hook handling for Codex and Claude Code."""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from .approval import AuthorityStore, approval_syntax, observe_human_event
from .canonical import canonical_text, compute_base_fingerprint, digest, normalize_path_text, plan_material, project_content_manifest, project_content_snapshot, project_identity
from .lifecycle import Phase, PhaseStatus, TerminalState, validate_not_applicable
from .policy import Decision, approved_scope_contains_paths, approved_scope_is_safe, approved_tool_guard, classify_tool
from .protocol import wire_result
from .state import RuntimeStore, done_guard_failures


SUPPORTED_EVENTS = {
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest",
    "SubagentStart", "SubagentStop", "Stop",
}
REVIEW_BEGIN = "MYTHOS_REVIEW_PACKET_V1_BEGIN"
REVIEW_END = "MYTHOS_REVIEW_PACKET_V1_END"
CRITIC_RECEIPT_BEGIN = "MYTHOS_CRITIC_RECEIPT_V1_BEGIN"
CRITIC_RECEIPT_END = "MYTHOS_CRITIC_RECEIPT_V1_END"
PLAN_BEGIN = "MYTHOS_APPROVAL_BUNDLE_V1_BEGIN"
PLAN_END = "MYTHOS_APPROVAL_BUNDLE_V1_END"
VERIFICATION_BEGIN = "MYTHOS_VERIFICATION_PACKET_V1_BEGIN"
VERIFICATION_END = "MYTHOS_VERIFICATION_PACKET_V1_END"
VERIFIER_RECEIPT_BEGIN = "MYTHOS_VERIFIER_RECEIPT_V1_BEGIN"
VERIFIER_RECEIPT_END = "MYTHOS_VERIFIER_RECEIPT_V1_END"
COMPLETION_BEGIN = "MYTHOS_COMPLETION_BUNDLE_V1_BEGIN"
COMPLETION_END = "MYTHOS_COMPLETION_BUNDLE_V1_END"
ATTEMPT_BEGIN = "MYTHOS_ATTEMPT_PACKET_V1_BEGIN"
ATTEMPT_END = "MYTHOS_ATTEMPT_PACKET_V1_END"
TERMINAL_BEGIN = "MYTHOS_TERMINAL_PACKET_V1_BEGIN"
TERMINAL_END = "MYTHOS_TERMINAL_PACKET_V1_END"
WAITING_MARKER = "MYTHOS_WAITING_FOR_HUMAN_V1"
REVIEWER_LAUNCH_PROMPT = (
    "Review only the hook-injected sealed packet. Do not use or request parent-session reasoning, "
    "a desired verdict, or an artifact summary."
)
PLANNING_FIELDS = (
    "schema_version", "run_id", "task_profile", "goal", "intake",
    "territory_discovery", "unknowns", "options", "acceptance_criteria",
    "plan", "mutation_scope",
)
VERIFICATION_FIELDS = (
    "schema_version", "run_id", "approval_bundle_hash", "implementation_notes",
    "increment_evidence", "acceptance_evidence", "reconciliation",
)
CRITIC_REQUIRED_SECTIONS = {
    "task_profile", "replan_provenance", "original_request", "context_manifest", "goal", "intake",
    "territory_discovery", "unknowns", "options", "acceptance_criteria", "plan", "mutation_scope",
}


def _result(
    decision: Decision,
    reason: str,
    *,
    host: str,
    event: str,
    context: str | None = None,
    system_message: str | None = None,
) -> dict[str, Any]:
    return wire_result(
        decision,
        reason,
        host=host,
        event=event,
        context=context,
        system_message=system_message,
    )


def _root(payload: dict[str, Any]) -> Path | None:
    value = os.environ.get("MYTHOS5_STATE_HOME")
    return Path(value).expanduser().resolve(strict=False) if value else None


def _run_id(payload: dict[str, Any], project: Path, session_id: str) -> str:
    return str(
        payload.get("run_id")
        or os.environ.get("MYTHOS_RUN_ID")
        or f"m5-{digest({'project': str(project), 'session': session_id})[:16]}"
    )


def _raw_material(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("evidence", {}).get("approval_material")
    if not isinstance(raw, dict) or not all(
        key in raw for key in ("plan", "scope", "acceptance", "critic", "base_fingerprint", "base_manifest")
    ):
        raise ValueError("approval_material evidence is incomplete")
    return raw


def _material(raw: dict[str, Any]) -> dict[str, str]:
    return plan_material(
        plan=raw["plan"],
        scope=raw["scope"],
        acceptance=raw["acceptance"],
        critic=raw["critic"],
        base_fingerprint=raw["base_fingerprint"],
    )


def _extract_json(text: str, begin: str, end: str) -> dict[str, Any] | None:
    if begin not in text:
        return None
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError(f"{begin} must appear exactly once with exactly one end marker")
    start = text.find(begin)
    finish = text.find(end, start + len(begin))
    if finish < 0:
        raise ValueError(f"{begin} has no matching end marker")
    body = text[start + len(begin):finish]
    left = body.find("{")
    right = body.rfind("}")
    if left < 0 or right < left:
        raise ValueError(f"{begin} does not contain a JSON object")
    value = json.loads(body[left:right + 1])
    if not isinstance(value, dict):
        raise ValueError("A Mythos bundle must be one JSON object")
    return value


def _nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


def _require_fields(value: dict[str, Any], fields: tuple[str, ...], label: str) -> None:
    missing = [field for field in fields if field not in value or not _nonempty(value[field])]
    if missing:
        raise ValueError(f"{label} is missing non-empty fields: {', '.join(missing)}")


def _require_present_fields(value: dict[str, Any], fields: tuple[str, ...], label: str) -> None:
    missing = [field for field in fields if field not in value]
    if missing:
        raise ValueError(f"{label} is missing fields: {', '.join(missing)}")


def _reject_extra_fields(value: dict[str, Any], allowed: set[str], label: str) -> None:
    extras = sorted(set(value).difference(allowed))
    if extras:
        raise ValueError(f"{label} contains unsupported fields: {', '.join(extras)}")


def _extract_receipt(text: str, begin: str, end: str, label: str) -> dict[str, Any]:
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError(f"{label} must contain exactly one receipt block")
    start = text.index(begin) + len(begin)
    finish = text.index(end, start)
    body = text[start:finish].strip()
    try:
        value = json.loads(body)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} receipt is not strict JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} receipt must be one JSON object")
    return value


def _textual_verdicts(output: str) -> list[str]:
    return re.findall(r"(?im)^\s*(?:-\s*)?Verdict:\s*([A-Z_]+)\s*$", output)


def _single_pass_verdict(output: str, label: str) -> None:
    if _textual_verdicts(output) != ["PASS"]:
        raise ValueError(f"{label} must contain exactly one textual `Verdict: PASS` and no contradictory verdict")


def _validate_planning_payload(
    bundle: dict[str, Any],
    *,
    run_id: str,
    project_root: Path,
    label: str,
    allowed_extra: tuple[str, ...] = (),
) -> None:
    _reject_extra_fields(bundle, set(PLANNING_FIELDS).union(allowed_extra), label)
    _require_fields(bundle, PLANNING_FIELDS, label)
    if bundle["schema_version"] != 1:
        raise ValueError(f"{label} schema_version must be 1")
    if bundle["run_id"] != run_id:
        raise ValueError(f"{label} belongs to another run")
    if bundle["task_profile"] not in {"build", "debug", "repair", "plan_only"}:
        raise ValueError(f"{label} task_profile is invalid")
    if not isinstance(bundle["goal"], str) or not bundle["goal"].strip():
        raise ValueError("goal must be a non-empty string")

    object_fields = ("intake", "territory_discovery", "unknowns", "options", "mutation_scope")
    for field in object_fields:
        if not isinstance(bundle[field], dict):
            raise ValueError(f"{field} must be an object")
    intake_fields = ("outcome", "scope", "constraints", "non_goals", "authorization")
    territory_fields = ("repository_map", "instructions", "conventions", "baseline")
    unknown_fields = ("known_knowns", "known_unknowns", "unknown_knowns", "unknown_unknowns", "blindspot_pass")
    scope_fields = ("paths", "commands", "external_effects")
    _reject_extra_fields(bundle["intake"], set(intake_fields), "intake")
    _reject_extra_fields(bundle["territory_discovery"], set(territory_fields), "territory discovery")
    _reject_extra_fields(bundle["unknowns"], set(unknown_fields), "unknowns")
    _reject_extra_fields(bundle["mutation_scope"], set(scope_fields), "mutation scope")
    _require_fields(bundle["intake"], intake_fields, "intake")
    _require_fields(bundle["territory_discovery"], territory_fields, "territory discovery")
    _require_fields(bundle["unknowns"], unknown_fields, "unknowns")
    _require_present_fields(bundle["mutation_scope"], scope_fields, "mutation scope")
    for field in ("outcome", "scope", "authorization"):
        if not isinstance(bundle["intake"][field], str) or not bundle["intake"][field].strip():
            raise ValueError(f"intake {field} must be a non-empty string")
    if not isinstance(bundle["territory_discovery"]["baseline"], str) or not bundle["territory_discovery"]["baseline"].strip():
        raise ValueError("territory discovery baseline must be a non-empty string")
    list_fields = (
        (bundle["intake"], ("constraints", "non_goals")),
        (bundle["territory_discovery"], ("repository_map", "instructions", "conventions")),
        (bundle["unknowns"], unknown_fields),
    )
    for container, fields in list_fields:
        for field in fields:
            if not isinstance(container[field], list) or not container[field] or not all(
                isinstance(item, str) and item.strip() for item in container[field]
            ):
                raise ValueError(f"{field} must be a non-empty string array")

    options = bundle["options"]
    _require_fields(options, ("status", "disposition"), "options")
    if options["status"] not in {"PASS", "NOT_APPLICABLE"}:
        raise ValueError("options status must be PASS or NOT_APPLICABLE")
    if not isinstance(options["disposition"], str) or not options["disposition"].strip():
        raise ValueError("options disposition must be a non-empty string")
    if options["status"] == "NOT_APPLICABLE":
        _reject_extra_fields(options, {"status", "disposition", "code", "reason", "evidence"}, "NOT_APPLICABLE options")
        _require_fields(options, ("code", "reason", "evidence"), "NOT_APPLICABLE options")
        if not isinstance(options["code"], str) or not isinstance(options["reason"], str):
            raise ValueError("NOT_APPLICABLE code and reason must be strings")
        if not isinstance(options["evidence"], dict) or not options["evidence"]:
            raise ValueError("NOT_APPLICABLE options evidence must be a non-empty object")
        validate_not_applicable(
            phase=Phase.OPTIONS_REFERENCES_OR_PROTOTYPES,
            profile=bundle["task_profile"],
            code=options["code"],
            reason=options["reason"],
            evidence=options["evidence"],
        )
    else:
        _reject_extra_fields(options, {"status", "disposition"}, "PASS options")

    for field in scope_fields:
        values = bundle["mutation_scope"][field]
        if not isinstance(values, list) or not all(isinstance(item, str) and item.strip() for item in values):
            raise ValueError(f"mutation scope {field} must be a string array")
    if not approved_scope_is_safe(project_root=project_root, scope=bundle["mutation_scope"]):
        raise ValueError("mutation scope paths must be portable relative paths inside the governed project and must not traverse reparse points")
    if bundle["mutation_scope"]["external_effects"]:
        raise ValueError("external_effects must be empty because this portable runtime cannot verify external systems")
    nonmutating_debug = bundle["task_profile"] == "debug" and not bundle["mutation_scope"]["paths"]
    if bundle["task_profile"] == "plan_only":
        if any(bundle["mutation_scope"][field] for field in scope_fields):
            raise ValueError("plan_only mutation scope paths, commands, and external_effects must all be empty")
    elif nonmutating_debug:
        pass
    elif not bundle["mutation_scope"]["paths"]:
        raise ValueError("a mutating profile requires at least one approved path")

    if not isinstance(bundle["acceptance_criteria"], list) or not bundle["acceptance_criteria"]:
        raise ValueError("acceptance_criteria must be a non-empty array")
    criterion_ids: set[str] = set()
    for criterion in bundle["acceptance_criteria"]:
        if not isinstance(criterion, dict):
            raise ValueError("each acceptance criterion must be an object")
        _reject_extra_fields(criterion, {"id", "pass_condition", "verification"}, "acceptance criterion")
        _require_fields(criterion, ("id", "pass_condition", "verification"), "acceptance criterion")
        for field in ("id", "pass_condition", "verification"):
            if not isinstance(criterion[field], str) or not criterion[field].strip():
                raise ValueError(f"acceptance criterion {field} must be a non-empty string")
        identifier = criterion["id"]
        if identifier in criterion_ids:
            raise ValueError(f"duplicate acceptance criterion id: {identifier}")
        criterion_ids.add(identifier)

    if not isinstance(bundle["plan"], list) or not bundle["plan"] or not all(isinstance(step, dict) for step in bundle["plan"]):
        raise ValueError("plan must be a non-empty array of objects")
    plan_ids: set[str] = set()
    for step in bundle["plan"]:
        _reject_extra_fields(step, {"id", "surfaces", "action", "verification", "rollback"}, "plan step")
        _require_present_fields(step, ("id", "surfaces", "action", "verification", "rollback"), "plan step")
        for field in ("id", "action", "verification", "rollback"):
            if not isinstance(step[field], str) or not step[field].strip():
                raise ValueError(f"plan step {field} must be a non-empty string")
        if step["id"] in plan_ids:
            raise ValueError(f"duplicate plan step id: {step['id']}")
        plan_ids.add(step["id"])
        if not isinstance(step["surfaces"], list) or not all(
            isinstance(surface, str) and surface.strip() for surface in step["surfaces"]
        ):
            raise ValueError("plan step surfaces must be a string array")
        if bundle["task_profile"] == "plan_only" or nonmutating_debug:
            if step["surfaces"]:
                raise ValueError("non-mutating plan steps must have empty mutation surfaces")
        elif not step["surfaces"]:
            raise ValueError("mutating plan steps require at least one surface")

def _review_packet_hash(bundle: dict[str, Any]) -> str:
    material = {field: bundle[field] for field in PLANNING_FIELDS}
    if "replan_from" in bundle:
        material["replan_from"] = bundle["replan_from"]
    return digest(material)


def _verification_packet_hash(bundle: dict[str, Any]) -> str:
    return digest({field: bundle[field] for field in VERIFICATION_FIELDS})


def _scope_contains_final_paths(project: Path, scope: dict[str, Any], final_scope: list[Any]) -> bool:
    if not all(isinstance(item, str) and item.strip() for item in final_scope):
        return False
    return approved_scope_contains_paths(
        project_root=project,
        scope=scope,
        candidates=final_scope,
    ) if final_scope else not scope.get("paths")

def _validate_acceptance_evidence(criteria: list[Any], evidence: list[Any]) -> None:
    expected = {item["id"] for item in criteria}
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("acceptance_evidence must be a non-empty array")
    seen: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError("each acceptance evidence entry must be an object")
        _reject_extra_fields(item, {"criterion", "evidence", "result"}, "acceptance evidence")
        _require_fields(item, ("criterion", "evidence", "result"), "acceptance evidence")
        if not isinstance(item["criterion"], str) or not item["criterion"].strip():
            raise ValueError("acceptance evidence criterion must be a non-empty string")
        if not isinstance(item["evidence"], str) or not item["evidence"].strip():
            raise ValueError("acceptance evidence evidence must be a non-empty string")
        identifier = item["criterion"]
        if identifier not in expected:
            raise ValueError(f"acceptance evidence names an unknown criterion: {identifier}")
        if identifier in seen:
            raise ValueError(f"acceptance evidence duplicates criterion: {identifier}")
        if item["result"] != "PASS":
            raise ValueError(f"acceptance criterion did not pass: {identifier}")
        seen.add(identifier)
    missing = sorted(expected.difference(seen))
    if missing:
        raise ValueError("acceptance evidence lacks PASS results for: " + ", ".join(missing))


def _validate_increment_evidence(plan: list[Any], evidence: list[Any], *, plan_only: bool) -> None:
    if plan_only:
        if evidence != []:
            raise ValueError("plan_only increment_evidence must be an empty array; do not fabricate implementation")
        return
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("increment_evidence must be a non-empty array")
    expected = {step["id"] for step in plan}
    seen: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError("each increment evidence entry must be an object")
        _reject_extra_fields(item, {"step", "evidence", "observation", "result"}, "increment evidence")
        _require_fields(item, ("step", "result"), "increment evidence")
        if not isinstance(item["step"], str) or not item["step"].strip():
            raise ValueError("increment evidence step must be a non-empty string")
        identifier = item["step"]
        if identifier not in expected:
            raise ValueError(f"increment evidence names an unknown plan step: {identifier}")
        if identifier in seen:
            raise ValueError(f"increment evidence duplicates plan step: {identifier}")
        proof = item.get("evidence", item.get("observation"))
        if not isinstance(proof, str) or not proof.strip():
            raise ValueError("increment evidence requires a non-empty string evidence or observation")
        if item["result"] != "PASS":
            raise ValueError(f"implementation increment did not pass: {identifier}")
        seen.add(identifier)
    missing = sorted(expected.difference(seen))
    if missing:
        raise ValueError("increment evidence lacks PASS results for plan steps: " + ", ".join(missing))


def _validate_reconciliation(
    value: dict[str, Any],
    *,
    plan: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    scope: dict[str, Any],
    actual_paths: list[str],
) -> None:
    if not isinstance(value, dict):
        raise ValueError("reconciliation must be an object")
    _reject_extra_fields(value, {"deviations"}, "submitted reconciliation")
    _require_fields(value, ("deviations",), "submitted reconciliation")
    if not isinstance(value["deviations"], list) or not value["deviations"]:
        raise ValueError("reconciliation deviations must be a non-empty array")
    allowed_classifications = {"MATCH", "NECESSARY_DEVIATION", "BENEFICIAL_DEVIATION"}
    valid_subjects = {
        "PLAN_STEP": {item["id"] for item in plan},
        "ACCEPTANCE_CRITERION": {item["id"] for item in criteria},
        "PATH": set(actual_paths),
        "COMMAND": set(scope["commands"]),
    }
    observed: set[tuple[str, str]] = set()
    for item in value["deviations"]:
        if not isinstance(item, dict):
            raise ValueError("each reconciliation deviation must be an object")
        _reject_extra_fields(
            item,
            {"subject_type", "subject_id", "classification", "evidence"},
            "reconciliation deviation",
        )
        _require_fields(
            item,
            ("subject_type", "subject_id", "classification", "evidence"),
            "reconciliation deviation",
        )
        subject_type = item["subject_type"]
        subject_id = item["subject_id"]
        if subject_type not in valid_subjects or subject_id not in valid_subjects[subject_type]:
            raise ValueError("reconciliation names an unknown or unobserved subject")
        key = (subject_type, subject_id)
        if key in observed:
            raise ValueError("reconciliation duplicates a subject")
        observed.add(key)
        if item["classification"] not in allowed_classifications:
            raise ValueError("reconciliation contains an unresolved or unsupported deviation")
        if not isinstance(item["evidence"], str) or not item["evidence"].strip():
            raise ValueError("reconciliation deviation evidence must be a non-empty string")
    missing_steps = sorted(valid_subjects["PLAN_STEP"].difference(
        subject_id for subject_type, subject_id in observed if subject_type == "PLAN_STEP"
    ))
    missing_paths = sorted(valid_subjects["PATH"].difference(
        subject_id for subject_type, subject_id in observed if subject_type == "PATH"
    ))
    if missing_steps or missing_paths:
        raise ValueError(
            "reconciliation must cover every approved plan step and hook-observed changed path; "
            f"missing_steps={missing_steps}, missing_paths={missing_paths}"
        )
def _changed_inventory(base: list[dict[str, str]], current: list[dict[str, str]]) -> list[dict[str, str]]:
    before = {item["path"]: item for item in base}
    after = {item["path"]: item for item in current}
    changes: list[dict[str, str]] = []
    for path in sorted(set(before).union(after)):
        old = before.get(path)
        new = after.get(path)
        if old == new:
            continue
        if old is None:
            changes.append({"path": path, "status": "ADDED", "after_kind": new["kind"], "after_sha256": new["sha256"]})
        elif new is None:
            changes.append({"path": path, "status": "DELETED", "before_kind": old["kind"], "before_sha256": old["sha256"]})
        else:
            changes.append({
                "path": path,
                "status": "MODIFIED",
                "before_kind": old["kind"],
                "before_sha256": old["sha256"],
                "after_kind": new["kind"],
                "after_sha256": new["sha256"],
            })
    return changes


def _content_delta(
    base_snapshot: list[dict[str, str]],
    current_snapshot: list[dict[str, str]],
    inventory: list[dict[str, str]],
) -> list[dict[str, Any]]:
    before = {item["path"]: item for item in base_snapshot}
    after = {item["path"]: item for item in current_snapshot}
    return [
        {
            "path": change["path"],
            "status": change["status"],
            "before": before.get(change["path"]),
            "after": after.get(change["path"]),
        }
        for change in inventory
    ]


def _scope_snapshot(project: Path, scope: dict[str, Any]) -> list[dict[str, str]]:
    """Capture every observable command surface, including generated roots."""

    return project_content_snapshot(
        project,
        include_paths=scope["paths"],
        include_generated=bool(scope["commands"]),
    )


def _scope_manifest(project: Path, scope: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"path": item["path"], "kind": item["kind"], "sha256": item["sha256"]}
        for item in _scope_snapshot(project, scope)
    ]


def _scope_fingerprint(project: Path, scope: dict[str, Any]) -> str:
    return digest(_scope_manifest(project, scope))


def _derive_actual_changes(
    project: Path,
    approval_material: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, Any]]]:
    current_snapshot = _scope_snapshot(project, approval_material["scope"])
    current_manifest = [
        {"path": item["path"], "kind": item["kind"], "sha256": item["sha256"]}
        for item in current_snapshot
    ]
    inventory = _changed_inventory(approval_material["base_manifest"], current_manifest)
    return inventory, current_manifest, _content_delta(
        approval_material["base_snapshot"], current_snapshot, inventory,
    )


def _unapproved_changed_paths(
    project: Path,
    approval_material: dict[str, Any],
) -> tuple[list[str], list[dict[str, str]], list[dict[str, str]], list[dict[str, Any]]]:
    inventory, current_manifest, content_delta = _derive_actual_changes(project, approval_material)
    actual = [item["path"] for item in inventory]
    if not actual or _scope_contains_final_paths(project, approval_material["scope"], actual):
        return [], inventory, current_manifest, content_delta
    unapproved = [
        path for path in actual
        if not approved_scope_contains_paths(
            project_root=project,
            scope=approval_material["scope"],
            candidates=[path],
        )
    ]
    return sorted(unapproved), inventory, current_manifest, content_delta


def _validate_actual_changes(
    project: Path,
    approval_material: dict[str, Any],
    *,
    mutation_expected: bool,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, Any]]]:
    unapproved, inventory, current_manifest, content_delta = _unapproved_changed_paths(
        project, approval_material,
    )
    if unapproved:
        raise ValueError(
            "hook-derived actual changed paths exceed the approved mutation paths: "
            + ", ".join(unapproved)
        )
    if not mutation_expected and inventory:
        raise ValueError("a no-mutation plan changed project content after approval")
    if mutation_expected and not inventory:
        raise ValueError("a mutating profile produced no hook-observed content change")
    return inventory, current_manifest, content_delta

def _validate_durable_attempts(
    state: dict[str, Any],
    plan: list[Any],
    approval_bundle_hash: str,
    *,
    plan_only: bool,
) -> None:
    if plan_only:
        return
    expected = {step["id"] for step in plan}
    passed = {
        item.get("step")
        for item in state.get("attempts", [])
        if item.get("approval_bundle_hash") == approval_bundle_hash
        and not item.get("failed")
        and item.get("evidence_gain") is True
        and item.get("scope_valid_at_close") is True
    }
    missing = sorted(expected.difference(passed))
    if missing:
        raise ValueError("durable attempt ledger lacks a passing evidence-gain record for: " + ", ".join(missing))

def _has_decision_packet(message: str) -> bool:
    """Accept only the exact bounded numbered A-D decision grammar."""

    lines = message.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    marker_lines = [index for index, line in enumerate(lines) if line == WAITING_MARKER]
    if any(WAITING_MARKER in line and line != WAITING_MARKER for line in lines):
        return False
    if marker_lines:
        if marker_lines != [len(lines) - 1]:
            return False
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()

    header = re.compile(r"^([1-9]\d*)\. \*\*(\S(?:.*\S)?)\*\*$")
    value = r"(\S(?:.*\S)?)"
    label = r"([^:\uff1a\s](?:[^:\uff1a]*[^:\uff1a\s])?)"
    localized_field = re.compile(r"^   - " + label + r"(?::|\uff1a) " + value + r"$")
    field_patterns = (
        localized_field,
        localized_field,
        re.compile(r"^   - A\. \*\*" + value + r"\*\* — " + value + r"$"),
        re.compile(r"^   - B\. (?!\*\*)" + value + r" — " + value + r"$"),
        re.compile(r"^   - C\. (?!\*\*)" + value + r" — " + value + r"$"),
        re.compile(r"^   - D\. (?!\*\*)" + value + r"$"),
        localized_field,
    )

    index = 0
    question_count = 0
    while index < len(lines):
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines):
            break
        match = header.fullmatch(lines[index])
        if match is None or int(match.group(1)) != question_count + 1:
            return False
        question_count += 1
        if question_count > 5:
            return False
        index += 1
        if index + len(field_patterns) > len(lines):
            return False
        localized_labels: list[str] = []
        for position, pattern in enumerate(field_patterns):
            line = lines[index]
            field_match = pattern.fullmatch(line)
            if field_match is None:
                return False
            if position in {0, 1, 6}:
                localized_labels.append(field_match.group(1).casefold())
            index += 1
        if len(set(localized_labels)) != 3:
            return False
        if index < len(lines) and lines[index].strip():
            return False

    return 1 <= question_count <= 5

def _read_only_exempt(prompt: str) -> bool:
    text = prompt.strip().casefold()
    if re.fullmatch(r"report\s+status[.?!]?", text):
        return True
    prefix = re.match(r"(explain|summarize|review|inspect|read|audit|analyze|check|answer|what\s+is|what\s+are|how\s+does)\s+", text)
    if prefix is None:
        return False
    body = text[prefix.end():]
    if body.endswith((".", "?", "!")):
        body = body[:-1].rstrip()
    if not body:
        return False
    safe_words = {
        "what", "the", "this", "that", "current", "existing", "repository", "repo", "project",
        "file", "files", "module", "modules", "code", "function", "functions", "class", "classes",
        "test", "tests", "status", "change", "changes", "error", "errors", "issue", "issues",
        "question", "plan", "result", "results", "output", "behavior", "configuration", "config",
        "log", "logs", "diff", "request", "response", "system", "workflow", "architecture", "purpose",
        "structure", "meaning", "does", "is", "are", "do", "works", "work", "contains", "contain",
        "uses", "use", "why", "of", "in", "for", "from",
    }
    token = re.compile(r"`[^`\r\n]+`|'[^'\r\n]+'|\"[^\"\r\n]+\"|[a-z]+")
    parts = token.findall(body)
    if not parts or " ".join(parts) != re.sub(r"\s+", " ", body):
        return False
    return all(part[0] in "`'\"" or part in safe_words for part in parts)

def _task_profile(prompt: str) -> str:
    lowered = prompt.casefold()
    if re.search(r"\b(debug|diagnose|investigate|root cause|reproduce)\b", lowered):
        return "debug"
    if re.search(r"\b(fix|repair|bug|defect|regression|error)\b", lowered):
        return "repair"
    if re.search(r"\b(plan|design|proposal|architecture)\b", lowered) and not re.search(
        r"\b(build|create|edit|implement|fix|repair|change|migrate)\b", lowered
    ):
        return "plan_only"
    return "build"


def _request_record(payload: dict[str, Any], message: str) -> dict[str, str]:
    return {
        "text": message,
        "request_hash": digest(message),
        "turn_id": str(payload.get("turn_id") or payload.get("message_id") or "unavailable"),
    }


def _tool_use_id(payload: dict[str, Any]) -> str | None:
    for key in ("tool_use_id", "toolUseId", "tool_call_id", "call_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
def _instruction_manifest(project: Path) -> list[dict[str, str]]:
    observed: list[dict[str, str]] = []
    if not project.exists():
        return observed

    def reparse(path: Path) -> bool:
        try:
            info = os.lstat(path)
        except OSError:
            return False
        attributes = int(getattr(info, "st_file_attributes", 0))
        flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
        return stat.S_ISLNK(info.st_mode) or bool(flag and attributes & flag)

    for directory, names, files in os.walk(project, followlinks=False):
        directory_path = Path(directory)
        retained: list[str] = []
        for name in sorted(names):
            candidate = directory_path / name
            relative = normalize_path_text(candidate.relative_to(project).as_posix(), platform="posix")
            if name == ".git":
                continue
            if reparse(candidate):
                lowered = relative.casefold()
                if lowered.startswith((".claude/rules", ".codex/rules", ".cursor/rules")):
                    observed.append({"path": relative, "kind": "reparse_directory", "sha256": digest(os.readlink(candidate) if candidate.is_symlink() else relative)})
                continue
            retained.append(name)
        names[:] = retained
        for name in sorted(files):
            path = directory_path / name
            relative = normalize_path_text(path.relative_to(project).as_posix(), platform="posix")
            lowered = relative.casefold()
            applicable = (
                path.name.casefold() in {"agents.md", "claude.md"}
                or lowered == ".github/copilot-instructions.md"
                or lowered.startswith((".claude/rules/", ".codex/rules/", ".cursor/rules/"))
            )
            if not applicable:
                continue
            if reparse(path):
                target = os.readlink(path) if path.is_symlink() else "WINDOWS_REPARSE_POINT"
                observed.append({"path": relative, "kind": "reparse_file", "target": target, "sha256": digest(target)})
                continue
            try:
                if path.stat().st_nlink > 1:
                    observed.append({"path": relative, "kind": "hardlink_file", "sha256": digest(relative)})
                    continue
                content = path.read_text(encoding="utf-8", errors="replace")
                observed.append({"path": relative, "kind": "file", "sha256": digest(content), "content": content})
            except OSError as error:
                observed.append({"path": relative, "kind": "unreadable", "sha256": digest(type(error).__name__)})
    return observed

def _context_manifest(
    state: dict[str, Any],
    project: Path,
    *,
    task_profile: str,
    instructions: list[str],
) -> dict[str, Any]:
    manifest = project_content_manifest(project)
    instruction_files = _instruction_manifest(project)
    unsafe = [item["path"] for item in instruction_files if item["kind"] != "file"]
    if unsafe:
        raise ValueError("governing instruction files must be regular readable files inside the governed root: " + ", ".join(unsafe))
    original = state.get("evidence", {}).get("original_request", {})
    latest = state.get("evidence", {}).get("latest_human_instruction", original)
    return {
        "project": state["project"],
        "project_fingerprint": compute_base_fingerprint(project),
        "content_manifest_hash": digest(manifest),
        "content_entry_count": len(manifest),
        "task_profile": task_profile,
        "original_request_hash": original.get("request_hash"),
        "latest_human_instruction": latest,
        "planner_declared_instructions": instructions,
        "hook_observed_instruction_files": instruction_files,
    }

def _reviewer_role_from_value(value: Any) -> str | None:
    token = str(value or "").strip().casefold().replace("_", "-")
    token = token.rsplit(":", 1)[-1]
    if token == "mythos-plan-critic":
        return "plan_critic"
    if token == "mythos-verifier":
        return "verifier"
    return None


def _agent_role(payload: dict[str, Any]) -> str | None:
    return _reviewer_role_from_value(payload.get("agent_type") or payload.get("subagent_type"))


def _reviewer_launch_role(tool_name: str, tool_input: dict[str, Any]) -> str | None:
    compact = re.sub(r"[^a-z0-9]", "", tool_name.casefold())
    if compact not in {"agent", "spawnagent", "collaborationspawnagent"} and not compact.endswith("spawnagent"):
        return None
    return _reviewer_role_from_value(
        tool_input.get("subagent_type") or tool_input.get("agent_type") or tool_input.get("task_name")
    )


def _record_reviewer_launch(
    store: RuntimeStore,
    state: dict[str, Any],
    *,
    session_id: str,
    host: str,
    tool_name: str,
    tool_input: dict[str, Any],
    project: Path,
) -> tuple[dict[str, Any], str | None, str | None]:
    role = _reviewer_launch_role(tool_name, tool_input)
    if role is None:
        return state, None, None
    allowed, reason = _agent_start_gate(state, role)
    if not allowed:
        return state, role, reason
    launch_prompt = str(tool_input.get("prompt") or tool_input.get("message") or "")
    if launch_prompt != REVIEWER_LAUNCH_PROMPT:
        return state, role, "independent reviewers require the exact neutral launch prompt"
    if host == "codex" and str(tool_input.get("fork_turns") or "").strip().casefold() != "none":
        return state, role, "Codex reviewer launch requires fork_turns=none in the observable spawn tool input"
    if host == "claude":
        selected = str(tool_input.get("subagent_type") or "").strip().casefold()
        if _reviewer_role_from_value(selected) != role or selected == "fork":
            return state, role, "Claude reviewer launch requires the dedicated named custom subagent, never type fork"
    packet_kind = "pending_review_packet" if role == "plan_critic" else "pending_verification_packet"
    packet = state.get("evidence", {}).get(packet_kind, {})
    value = {
        "active": True,
        "consumed": False,
        "host": host,
        "session_id": session_id,
        "role": role,
        "requested_agent_type": (
            tool_input.get("subagent_type") or tool_input.get("agent_type") or tool_input.get("task_name")
        ),
        "packet_hash": packet.get("hash"),
        "project_fingerprint": compute_base_fingerprint(project),
        "launch_prompt_hash": digest(launch_prompt),
        "tool_input_hash": digest(tool_input),
        "isolation_contract": (
            "named-custom-agent-fresh-context" if host == "claude" else "observable-fork-turns-none"
        ),
    }
    state = store.record_evidence(session_id=session_id, kind=f"pending_{role}_launch", value=value)
    return state, role, None


def _normalized_transcript_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None


def _separate_subagent_transcript(active: dict[str, Any], payload: dict[str, Any]) -> tuple[bool, str | None]:
    main_at_start = _normalized_transcript_path(active.get("parent_transcript_path"))
    main_at_stop = _normalized_transcript_path(payload.get("transcript_path"))
    agent_path = _normalized_transcript_path(payload.get("agent_transcript_path"))
    if main_at_start is None or main_at_stop is None or agent_path is None:
        return False, None
    if os.path.normcase(str(main_at_start)) != os.path.normcase(str(main_at_stop)):
        return False, str(agent_path)
    if os.path.normcase(str(main_at_stop)) == os.path.normcase(str(agent_path)):
        return False, str(agent_path)
    expected_root = main_at_stop.parent / main_at_stop.stem / "subagents"
    try:
        nested = os.path.normcase(os.path.commonpath([str(agent_path), str(expected_root)])) == os.path.normcase(str(expected_root))
    except ValueError:
        nested = False
    return bool(nested and agent_path.suffix.casefold() == ".jsonl"), str(agent_path)


def _record_agent_event(
    store: RuntimeStore,
    state: dict[str, Any],
    *,
    session_id: str,
    event: str,
    payload: dict[str, Any],
    project: Path,
    host: str,
) -> dict[str, Any]:
    role = _agent_role(payload)
    if role is None:
        return state
    raw_agent_id = payload.get("agent_id")
    agent_id = str(raw_agent_id or digest(payload)[:24])
    packet_kind = "pending_review_packet" if role == "plan_critic" else "pending_verification_packet"
    pending_packet = state.get("evidence", {}).get(packet_kind, {})
    launch_kind = f"pending_{role}_launch"
    launch = state.get("evidence", {}).get(launch_kind, {})
    if event == "SubagentStart":
        agent_type = payload.get("agent_type") or payload.get("subagent_type")
        launch_matches = (
            isinstance(launch, dict)
            and launch.get("active") is True
            and launch.get("consumed") is False
            and launch.get("host") == host
            and launch.get("session_id") == session_id
            and launch.get("role") == role
            and launch.get("packet_hash") == pending_packet.get("hash")
            and launch.get("project_fingerprint") == compute_base_fingerprint(project)
            and raw_agent_id not in (None, "")
        )
        prior = state.get("evidence", {}).get(f"latest_{role}", {})
        if isinstance(prior, dict) and prior.get("agent_id") == agent_id:
            launch_matches = False
        isolation_text = str(launch.get("isolation_contract") or "missing-observable-launch-intent")
        active = {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "event": event,
            "host": host,
            "context_isolation": isolation_text,
            "isolation_verified": bool(launch_matches),
            "parent_transcript_path": payload.get("transcript_path"),
            "project_fingerprint": compute_base_fingerprint(project),
            "packet_hash": pending_packet.get("hash"),
            "packet": pending_packet.get("packet"),
            "launch_tool_input_hash": launch.get("tool_input_hash"),
        }
        operations = [{"operation": "record_evidence", "kind": f"active_{role}", "value": active}]
        if launch_matches:
            operations.append({
                "operation": "record_evidence",
                "kind": launch_kind,
                "value": {**launch, "active": False, "consumed": True, "agent_id": agent_id},
            })
        return store.apply_batch(session_id=session_id, operations=operations)
    active = state.get("evidence", {}).get(f"active_{role}", {})
    output = str(payload.get("last_assistant_message") or payload.get("message") or "")
    transcript_verified, agent_transcript_path = _separate_subagent_transcript(active, payload)
    identity_matches = (
        active.get("agent_id") == agent_id
        and active.get("host") == host
        and _reviewer_role_from_value(active.get("agent_type")) == role
        and active.get("isolation_verified") is True
    )
    isolation_verified = bool(identity_matches and transcript_verified)
    return store.record_evidence(
        session_id=session_id,
        kind=f"latest_{role}",
        value={
            "agent_id": agent_id,
            "agent_type": payload.get("agent_type"),
            "event": event,
            "fresh_start_matched": isolation_verified,
            "context_isolation": active.get("context_isolation"),
            "isolation_verified": isolation_verified,
            "agent_transcript_path": agent_transcript_path,
            "output": output,
            "output_hash": digest(output),
            "project_fingerprint": active.get("project_fingerprint"),
            "packet_hash": active.get("packet_hash"),
            "packet_hash_at_start": digest(active.get("packet")) if isinstance(active.get("packet"), dict) else None,
        },
    )


def _validate_critic_receipt(output: str, packet_hash: str) -> dict[str, Any]:
    _single_pass_verdict(output, "plan critic")
    receipt = _extract_receipt(output, CRITIC_RECEIPT_BEGIN, CRITIC_RECEIPT_END, "plan critic")
    allowed = {
        "schema_version", "packet_hash", "verdict", "reviewed_sections",
        "blocking_findings", "high_findings", "context_contamination",
    }
    _reject_extra_fields(receipt, allowed, "plan critic receipt")
    _require_fields(receipt, ("schema_version", "packet_hash", "verdict", "reviewed_sections"), "plan critic receipt")
    if receipt["schema_version"] != 1 or receipt["packet_hash"] != packet_hash or receipt["verdict"] != "PASS":
        raise ValueError("plan critic receipt schema, packet binding, or verdict is invalid")
    sections = receipt["reviewed_sections"]
    if not isinstance(sections, list) or len(sections) != len(set(sections)) or set(sections) != CRITIC_REQUIRED_SECTIONS:
        raise ValueError("plan critic receipt reviewed_sections must cover every canonical sealed section exactly once")
    for field in ("blocking_findings", "high_findings", "context_contamination"):
        if field not in receipt or not isinstance(receipt[field], list) or receipt[field]:
            raise ValueError(f"plan critic receipt {field} must be an explicit empty array for PASS")
    return receipt


def _validate_verifier_receipt(
    output: str,
    packet_hash: str,
    criteria: list[Any],
) -> dict[str, Any]:
    _single_pass_verdict(output, "verifier")
    receipt = _extract_receipt(output, VERIFIER_RECEIPT_BEGIN, VERIFIER_RECEIPT_END, "verifier")
    allowed = {
        "schema_version", "packet_hash", "verdict", "criteria",
        "scope_matches_approval", "approval_current", "blocking_findings",
        "high_findings", "context_contamination",
    }
    _reject_extra_fields(receipt, allowed, "verifier receipt")
    _require_fields(
        receipt,
        ("schema_version", "packet_hash", "verdict", "criteria", "scope_matches_approval", "approval_current"),
        "verifier receipt",
    )
    if receipt["schema_version"] != 1 or receipt["packet_hash"] != packet_hash or receipt["verdict"] != "PASS":
        raise ValueError("verifier receipt schema, packet binding, or verdict is invalid")
    if receipt["scope_matches_approval"] is not True or receipt["approval_current"] is not True:
        raise ValueError("verifier receipt must affirm current approval and approved scope")
    expected = {str(item["id"]) for item in criteria}
    observed: set[str] = set()
    if not isinstance(receipt["criteria"], list) or not receipt["criteria"]:
        raise ValueError("verifier receipt criteria must be a non-empty array")
    for item in receipt["criteria"]:
        if not isinstance(item, dict):
            raise ValueError("each verifier receipt criterion must be an object")
        _reject_extra_fields(item, {"criterion", "result", "evidence"}, "verifier receipt criterion")
        _require_fields(item, ("criterion", "result", "evidence"), "verifier receipt criterion")
        if not isinstance(item["criterion"], str) or not item["criterion"].strip():
            raise ValueError("verifier receipt criterion must be a non-empty string")
        if not isinstance(item["evidence"], str) or not item["evidence"].strip():
            raise ValueError("verifier receipt evidence must be a non-empty string")
        identifier = item["criterion"]
        if identifier not in expected or identifier in observed or item["result"] != "PASS":
            raise ValueError(f"verifier receipt criterion is unknown, duplicate, or non-PASS: {identifier}")
        observed.add(identifier)
    if observed != expected:
        raise ValueError("verifier receipt does not cover every acceptance criterion exactly once")
    for field in ("blocking_findings", "high_findings", "context_contamination"):
        if field not in receipt or not isinstance(receipt[field], list) or receipt[field]:
            raise ValueError(f"verifier receipt {field} must be an explicit empty array for PASS")
    return receipt


def _agent_start_gate(state: dict[str, Any], role: str) -> tuple[bool, str]:
    packet_kind = "pending_review_packet" if role == "plan_critic" else "pending_verification_packet"
    pending = state.get("evidence", {}).get(packet_kind, {})
    if not isinstance(pending, dict) or pending.get("active") is not True:
        return False, f"no active hook-sealed {role.replace('_', ' ')} packet is available"
    if pending.get("reviewed") is True:
        return False, f"the sealed {role.replace('_', ' ')} packet already has a terminal review result"
    if role == "verifier" and state.get("phase") != Phase.IMPLEMENTATION_LOOP.value:
        return False, "a verifier may start only from an active IMPLEMENTATION_LOOP"
    return True, "review start is bound to the active sealed packet"


def _adjudicate_agent_stop(
    store: RuntimeStore,
    state: dict[str, Any],
    *,
    session_id: str,
    role: str,
    project: Path,
    authority: AuthorityStore,
) -> tuple[dict[str, Any], bool, str]:
    packet_kind = "pending_review_packet" if role == "plan_critic" else "pending_verification_packet"
    latest_kind = f"latest_{role}"
    accepted_kind = "accepted_plan_critic" if role == "plan_critic" else "accepted_verifier"
    pending = state.get("evidence", {}).get(packet_kind, {})
    latest = state.get("evidence", {}).get(latest_kind, {})
    packet_hash = pending.get("hash")
    try:
        if not isinstance(pending, dict) or pending.get("active") is not True or pending.get("reviewed") is True:
            raise ValueError("the sealed packet is missing, inactive, or already reviewed")
        if not isinstance(latest, dict) or latest.get("fresh_start_matched") is not True:
            raise ValueError("the reviewer stop does not match a host-verified fresh start")
        if latest.get("packet_hash") != packet_hash or latest.get("packet_hash_at_start") != packet_hash:
            raise ValueError("the reviewer did not receive the exact active sealed packet")
        if latest.get("project_fingerprint") != pending.get("project_fingerprint"):
            raise ValueError("the reviewer started against a different project fingerprint")
        if compute_base_fingerprint(project) != pending.get("project_fingerprint"):
            raise ValueError("the project changed while the independent review was active")
        output = str(latest.get("output", ""))
        if role == "plan_critic":
            receipt = _validate_critic_receipt(output, str(packet_hash))
        else:
            packet = pending.get("packet", {})
            criteria = packet.get("acceptance_criteria") if isinstance(packet, dict) else None
            if not isinstance(criteria, list):
                raise ValueError("the sealed verifier packet has no acceptance criteria")
            receipt = _validate_verifier_receipt(output, str(packet_hash), criteria)
    except Exception as error:
        reason = str(error)
        rejected_pending = {
            **pending,
            "active": False,
            "reviewed": True,
            "review_result": "REJECTED",
            "rejection_reason": reason,
            "rejected_output_hash": latest.get("output_hash") if isinstance(latest, dict) else None,
        }
        operations: list[dict[str, Any]] = [
            {"operation": "record_evidence", "kind": packet_kind, "value": rejected_pending},
            {
                "operation": "record_evidence",
                "kind": f"{role}_rejection",
                "value": {
                    "packet_hash": packet_hash,
                    "reason": reason,
                    "verdicts": _textual_verdicts(str(latest.get("output", ""))) if isinstance(latest, dict) else [],
                    "output_hash": latest.get("output_hash") if isinstance(latest, dict) else None,
                    "required_reentry": Phase.UNKNOWNS_AND_BLINDSPOTS.value if role == "verifier" else "NEW_REVIEW_PACKET",
                },
            },
        ]
        if role == "verifier":
            authority.invalidate(["independent verifier returned non-PASS or an invalid PASS"])
            operations.append({
                "operation": "transition",
                "to_phase": Phase.UNKNOWNS_AND_BLINDSPOTS.value,
                "reason": "Every verifier non-PASS or invalid PASS requires phase-3 replanning, a fresh critic, and new human approval",
                "evidence": {"packet_hash": packet_hash, "reason": reason},
            })
        state = store.apply_batch(session_id=session_id, operations=operations)
        if role == "verifier":
            state = store.set_terminal(
                session_id=session_id,
                terminal_state=TerminalState.VERIFICATION_FAILED,
                reason="Independent verification rejected the sealed result",
                evidence={"packet_hash": packet_hash, "rejection_reason": reason},
                resume_condition="The human acknowledges the failed verification before phase-3 replanning",
            )
        return state, False, reason

    accepted = {**latest, "receipt": receipt}
    accepted_pending = {
        **pending,
        "reviewed": True,
        "review_result": "PASS",
        "accepted_output_hash": latest["output_hash"],
    }
    state = store.apply_batch(
        session_id=session_id,
        operations=[
            {"operation": "record_evidence", "kind": accepted_kind, "value": accepted},
            {"operation": "record_evidence", "kind": packet_kind, "value": accepted_pending},
        ],
    )
    return state, True, "the fresh-context reviewer returned one valid packet-bound PASS"

def _ingest_review_packet(
    store: RuntimeStore,
    state: dict[str, Any],
    *,
    session_id: str,
    run_id: str,
    project: Path,
    authority: AuthorityStore,
    packet: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    if state.get("terminal_state") is not None:
        raise ValueError("resume the explicit terminal state before sealing a review packet")
    if state.get("evidence", {}).get("pending_attempt", {}).get("active") is True:
        raise ValueError("finish the pending substantive act with an exact attempt packet before sealing a replan review")
    _validate_planning_payload(packet, run_id=run_id, project_root=project, label="review packet", allowed_extra=("replan_from",))
    current = Phase(state["phase"])
    if current not in {
        Phase.INTAKE,
        Phase.AWAITING_HUMAN_PLAN_APPROVAL,
        Phase.IMPLEMENTATION_LOOP,
        Phase.INDEPENDENT_VERIFICATION,
        Phase.UNKNOWNS_AND_BLINDSPOTS,
    }:
        raise ValueError(f"review packet cannot be sealed from phase {current.value}")
    if current is Phase.INTAKE:
        if "replan_from" in packet:
            raise ValueError("an initial review packet must not declare replan_from")
        if state["task_profile"] != packet["task_profile"]:
            state = store.set_task_profile(session_id=session_id, task_profile=packet["task_profile"])
    elif packet.get("replan_from") != Phase.UNKNOWNS_AND_BLINDSPOTS.value:
        raise ValueError("every reapproval must restart at UNKNOWNS_AND_BLINDSPOTS")
    if current is not Phase.INTAKE:
        prior = _raw_material(state)
        unapproved, inventory, _, _ = _unapproved_changed_paths(project, prior)
        if unapproved:
            authority.invalidate(["unapproved project delta must be reverted before replanning"])
            store.record_evidence(
                session_id=session_id,
                kind="scope_violation",
                value={
                    "unapproved_paths": unapproved,
                    "changed_inventory": inventory,
                    "required_action": "Revert the unapproved delta before sealing any new baseline",
                },
            )
            raise ValueError(
                "unapproved project delta cannot become a reapproval baseline; revert: "
                + ", ".join(unapproved)
            )
    original_request = state.get("evidence", {}).get("original_request")
    if not isinstance(original_request, dict) or not original_request.get("text"):
        raise ValueError("the hook did not observe an original substantive human request")
    context_manifest = _context_manifest(
        state,
        project,
        task_profile=packet["task_profile"],
        instructions=packet["territory_discovery"]["instructions"],
    )
    sealed_packet = {
        **packet,
        "replan_provenance": {
            "kind": "initial" if current is Phase.INTAKE else "reapproval",
            "from": packet.get("replan_from"),
        },
        "original_request": original_request,
        "context_manifest": context_manifest,
    }
    submitted_hash = _review_packet_hash(packet)
    packet_hash = digest(sealed_packet)
    authority.invalidate(["a new independent plan-review packet was sealed"])
    state = store.record_evidence(
        session_id=session_id,
        kind="pending_review_packet",
        value={
            "active": True,
            "reviewed": False,
            "hash": packet_hash,
            "submitted_hash": submitted_hash,
            "project_fingerprint": context_manifest["project_fingerprint"],
            "packet": sealed_packet,
            "planning_packet": packet,
        },
    )
    return state, packet_hash


def _validated_plan_bundle(
    bundle: dict[str, Any],
    *,
    run_id: str,
    state: dict[str, Any],
    project: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _validate_planning_payload(
        bundle, run_id=run_id, project_root=project, label="approval bundle",
        allowed_extra=("critic", "review_packet_hash", "replan_from"),
    )
    _require_fields(bundle, ("critic", "review_packet_hash"), "approval bundle")
    if not isinstance(bundle["critic"], dict):
        raise ValueError("critic must be an object")
    _reject_extra_fields(bundle["critic"], {"adjudication"}, "critic")
    _require_fields(bundle["critic"], ("adjudication",), "critic")
    adjudication = bundle["critic"]["adjudication"]
    if not isinstance(adjudication, list) or not adjudication or not all(isinstance(item, dict) for item in adjudication):
        raise ValueError("critic adjudication must be a non-empty array of objects")
    pending = state.get("evidence", {}).get("pending_review_packet")
    if not isinstance(pending, dict):
        raise ValueError("no hook-sealed review packet exists")
    if pending.get("reviewed") is not True or pending.get("review_result") != "PASS":
        raise ValueError("the latest sealed review packet has no accepted terminal PASS")
    submitted_hash = _review_packet_hash(bundle)
    if submitted_hash != pending.get("submitted_hash"):
        raise ValueError("approval bundle planning fields differ from the submitted review packet")
    packet_hash = pending.get("hash")
    if bundle["review_packet_hash"] != packet_hash:
        raise ValueError("approval bundle does not match the latest hook-sealed review_packet_hash")
    review = state.get("evidence", {}).get("accepted_plan_critic")
    if not isinstance(review, dict) or not review.get("fresh_start_matched"):
        raise ValueError("no matching fresh-context plan critic receipt was observed")
    if review.get("packet_hash") != packet_hash:
        raise ValueError("plan critic receipt belongs to a different review packet")
    if review.get("packet_hash_at_start") != packet_hash:
        raise ValueError("the exact sealed review packet was not injected at critic start")
    if review.get("project_fingerprint") != pending.get("project_fingerprint"):
        raise ValueError("plan critic started against a different project fingerprint than the sealed packet")
    receipt = _validate_critic_receipt(str(review.get("output", "")), packet_hash)
    review = {**review, "receipt": receipt}
    return bundle, review

def _ingest_plan_bundle(
    store: RuntimeStore,
    state: dict[str, Any],
    *,
    session_id: str,
    run_id: str,
    project: Path,
    authority: AuthorityStore,
    bundle: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    if state.get("evidence", {}).get("pending_attempt", {}).get("active") is True:
        raise ValueError("finish the pending substantive act with an exact attempt packet before replanning")
    if Phase(state["phase"]) is not Phase.INTAKE:
        prior = _raw_material(state)
        unapproved, inventory, _, _ = _unapproved_changed_paths(project, prior)
        if unapproved:
            authority.invalidate(["unapproved project delta must be reverted before reapproval"])
            store.record_evidence(
                session_id=session_id,
                kind="scope_violation",
                value={
                    "unapproved_paths": unapproved,
                    "changed_inventory": inventory,
                    "required_action": "Revert the unapproved delta before approving any new baseline",
                },
            )
            raise ValueError(
                "unapproved project delta cannot become a reapproval baseline; revert: "
                + ", ".join(unapproved)
            )
    bundle, review = _validated_plan_bundle(bundle, run_id=run_id, state=state, project=project)
    pending_review = state["evidence"]["pending_review_packet"]
    current_fingerprint = compute_base_fingerprint(project)
    if pending_review["project_fingerprint"] != current_fingerprint:
        raise ValueError("project changed after the plan review packet was sealed")
    if review.get("project_fingerprint") != current_fingerprint:
        raise ValueError("plan critic reviewed a different working tree")
    if state["task_profile"] != bundle["task_profile"]:
        raise ValueError("task_profile cannot change after the review packet is sealed; start a new run")

    sealed_review = pending_review["packet"]
    base_snapshot = _scope_snapshot(project, bundle["mutation_scope"])
    base_manifest = [
        {"path": item["path"], "kind": item["kind"], "sha256": item["sha256"]}
        for item in base_snapshot
    ]
    raw = {
        "task_profile": bundle["task_profile"],
        "original_request": sealed_review["original_request"],
        "applicable_instructions": {
            "planner_declared": bundle["territory_discovery"]["instructions"],
            "hook_observed": sealed_review["context_manifest"]["hook_observed_instruction_files"],
        },
        "goal": bundle["goal"],
        "intake": bundle["intake"],
        "territory_discovery": bundle["territory_discovery"],
        "unknowns": bundle["unknowns"],
        "options": bundle["options"],
        "plan": bundle["plan"],
        "scope": bundle["mutation_scope"],
        "acceptance": bundle["acceptance_criteria"],
        "critic": {"review": review, "adjudication": bundle["critic"]["adjudication"]},
        "review_packet_hash": bundle["review_packet_hash"],
        "base_fingerprint": current_fingerprint,
        "base_manifest": base_manifest,
        "base_snapshot": base_snapshot,
        "base_scope_fingerprint": digest(base_manifest),
        "context_manifest": sealed_review["context_manifest"],
    }
    operations: list[dict[str, Any]] = [
        {"operation": "record_evidence", "kind": "intake", "value": bundle["intake"]},
        {"operation": "record_evidence", "kind": "territory_discovery", "value": bundle["territory_discovery"]},
        {"operation": "record_evidence", "kind": "unknowns_and_blindspots", "value": bundle["unknowns"]},
        {"operation": "record_evidence", "kind": "options_references_or_prototypes", "value": bundle["options"]},
        {"operation": "record_evidence", "kind": "acceptance_criteria", "value": bundle["acceptance_criteria"]},
        {"operation": "record_evidence", "kind": "implementation_plan", "value": bundle["plan"]},
        {"operation": "record_evidence", "kind": "independent_plan_critique", "value": {"review": review, "adjudication": bundle["critic"]["adjudication"]}},
        {"operation": "record_evidence", "kind": "review_packet_receipt", "value": {"hash": bundle["review_packet_hash"], "critic_output_hash": review["output_hash"]}},
        {"operation": "record_evidence", "kind": "pending_plan_feedback", "value": {"status": "cleared", "by_review_packet_hash": bundle["review_packet_hash"]}},
    ]
    current = Phase(state["phase"])
    if current is Phase.INTAKE:
        operations.extend([
            {"operation": "transition", "to_phase": Phase.TERRITORY_DISCOVERY.value, "evidence": bundle["intake"]},
            {"operation": "transition", "to_phase": Phase.UNKNOWNS_AND_BLINDSPOTS.value, "evidence": bundle["territory_discovery"]},
        ])
    elif current is Phase.UNKNOWNS_AND_BLINDSPOTS:
        if bundle.get("replan_from") != Phase.UNKNOWNS_AND_BLINDSPOTS.value:
            raise ValueError("every reapproval bundle must restart at UNKNOWNS_AND_BLINDSPOTS")
    elif current in {Phase.AWAITING_HUMAN_PLAN_APPROVAL, Phase.IMPLEMENTATION_LOOP, Phase.INDEPENDENT_VERIFICATION}:
        if bundle.get("replan_from") != Phase.UNKNOWNS_AND_BLINDSPOTS.value:
            raise ValueError("every reapproval bundle must restart at UNKNOWNS_AND_BLINDSPOTS")
        operations.append({
            "operation": "transition",
            "to_phase": Phase.UNKNOWNS_AND_BLINDSPOTS.value,
            "reason": "Material discovery or review requires a complete phase-3 re-entry",
        })
    else:
        raise ValueError(f"approval bundle cannot be ingested from phase {current.value}")
    operations.append({
        "operation": "transition",
        "to_phase": Phase.OPTIONS_REFERENCES_OR_PROTOTYPES.value,
        "evidence": bundle["unknowns"],
    })
    options = bundle["options"]
    if options["status"] == "NOT_APPLICABLE":
        operations.append({
            "operation": "transition",
            "to_phase": Phase.ACCEPTANCE_CRITERIA.value,
            "outcome": PhaseStatus.NOT_APPLICABLE.value,
            "reason": options["reason"],
            "not_applicable_code": options["code"],
            "evidence": options["evidence"],
        })
    else:
        operations.append({"operation": "transition", "to_phase": Phase.ACCEPTANCE_CRITERIA.value, "evidence": options})
    operations.extend([
        {"operation": "transition", "to_phase": Phase.IMPLEMENTATION_PLAN.value, "evidence": {"criteria": bundle["acceptance_criteria"]}},
        {"operation": "transition", "to_phase": Phase.INDEPENDENT_PLAN_CRITIQUE.value, "evidence": {"plan": bundle["plan"], "scope": bundle["mutation_scope"]}},
        {"operation": "transition", "to_phase": Phase.AWAITING_HUMAN_PLAN_APPROVAL.value, "evidence": {"critic_receipt": review["output_hash"]}},
        {"operation": "record_evidence", "kind": "approval_material", "value": raw},
    ])
    authority.invalidate(["a new approval bundle was prepared"])
    state = store.apply_batch(session_id=session_id, operations=operations)
    material = _material(raw)
    expected = approval_syntax(run_id, material["bundle_hash"])
    state = store.set_terminal(
        session_id=session_id,
        terminal_state=TerminalState.AWAITING_HUMAN_PLAN_APPROVAL,
        reason="The exact independently reviewed plan is waiting for explicit human approval",
        evidence={"bundle_hash": material["bundle_hash"], "approval_syntax_hash": digest(expected)},
        resume_condition="The human sends the exact hook-issued approval statement or supplies plan feedback",
    )
    return state, expected

def _ingest_verification_packet(
    store: RuntimeStore,
    state: dict[str, Any],
    *,
    session_id: str,
    run_id: str,
    project: Path,
    authority: AuthorityStore,
    packet: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    if state["phase"] != Phase.IMPLEMENTATION_LOOP.value or state.get("terminal_state") is not None:
        raise ValueError("verification packet is accepted only during an active IMPLEMENTATION_LOOP")
    if state.get("evidence", {}).get("pending_attempt", {}).get("active") is True:
        raise ValueError("verification cannot begin until the pending substantive act has an exact attempt packet")
    _reject_extra_fields(packet, set(VERIFICATION_FIELDS), "verification packet")
    _require_present_fields(packet, VERIFICATION_FIELDS, "verification packet")
    if packet["schema_version"] != 1 or packet["run_id"] != run_id:
        raise ValueError("verification packet schema or run binding is invalid")
    raw = _raw_material(state)
    material = _material(raw)
    if packet["approval_bundle_hash"] != material["bundle_hash"]:
        raise ValueError("verification packet belongs to another approval bundle")
    valid, reasons, _ = authority.validate(
        run_id=run_id,
        session_id=session_id,
        project=store.identity,
        material=material,
    )
    if not valid:
        raise ValueError("current approval is invalid: " + "; ".join(reasons))
    if not isinstance(packet["implementation_notes"], dict) or not packet["implementation_notes"]:
        raise ValueError("implementation_notes must be a non-empty object")
    plan_only = raw["task_profile"] == "plan_only"
    mutation_expected = not plan_only and not (raw["task_profile"] == "debug" and not raw["scope"]["paths"])
    _validate_increment_evidence(raw["plan"], packet["increment_evidence"], plan_only=plan_only)
    _validate_durable_attempts(state, raw["plan"], material["bundle_hash"], plan_only=plan_only)
    if not plan_only:
        bound_attempts = [
            item for item in state.get("attempts", [])
            if item.get("approval_bundle_hash") == material["bundle_hash"]
        ]
        current_scope_fingerprint = _scope_fingerprint(project, raw["scope"])
        if not bound_attempts or bound_attempts[-1].get("project_fingerprint") != current_scope_fingerprint:
            raise ValueError("project content changed after the latest durable attempt; record a new bounded attempt before verification")
    _validate_acceptance_evidence(raw["acceptance"], packet["acceptance_evidence"])
    current_fingerprint = compute_base_fingerprint(project)
    inventory, current_manifest, content_delta = _validate_actual_changes(
        project,
        raw,
        mutation_expected=mutation_expected,
    )
    _validate_reconciliation(
        packet["reconciliation"],
        plan=raw["plan"],
        criteria=raw["acceptance"],
        scope=raw["scope"],
        actual_paths=[item["path"] for item in inventory],
    )
    hook_reconciliation = {
        "deviations": packet["reconciliation"]["deviations"],
        "final_scope": [item["path"] for item in inventory],
        "final_fingerprint": current_fingerprint,
    }
    context_manifest = _context_manifest(
        state,
        project,
        task_profile=raw["task_profile"],
        instructions=raw["applicable_instructions"]["planner_declared"],
    )
    if context_manifest["hook_observed_instruction_files"] != raw["applicable_instructions"]["hook_observed"]:
        raise ValueError("project-local governing instructions changed after approval; re-plan before verification")
    sealed_packet = {
        **packet,
        "reconciliation": hook_reconciliation,
        "task_profile": raw["task_profile"],
        "original_request": raw["original_request"],
        "goal": raw["goal"],
        "intake": raw["intake"],
        "territory_discovery": raw["territory_discovery"],
        "unknowns": raw["unknowns"],
        "options": raw["options"],
        "applicable_instructions": raw["applicable_instructions"],
        "approved_plan": raw["plan"],
        "approved_mutation_scope": raw["scope"],
        "acceptance_criteria": raw["acceptance"],
        "base_fingerprint": raw["base_fingerprint"],
        "final_fingerprint": current_fingerprint,
        "base_manifest_hash": digest(raw["base_manifest"]),
        "final_manifest_hash": digest(current_manifest),
        "changed_inventory": inventory,
        "content_delta": content_delta,
        "context_manifest": context_manifest,
    }
    packet_hash = digest(sealed_packet)
    state = store.record_evidence(
        session_id=session_id,
        kind="pending_verification_packet",
        value={
            "active": True,
            "reviewed": False,
            "hash": packet_hash,
            "project_fingerprint": current_fingerprint,
            "approval_bundle_hash": material["bundle_hash"],
            "packet": sealed_packet,
            "submitted_packet": packet,
        },
    )
    return state, packet_hash


def _validated_completion_bundle(
    bundle: dict[str, Any],
    *,
    run_id: str,
    state: dict[str, Any],
    project: Path,
    approval_material: dict[str, Any],
    approval_bundle_hash: str,
) -> dict[str, Any]:
    completion_fields = {
        "schema_version", "run_id", "verification_packet_hash", "implementation_notes",
        "increment_evidence", "acceptance_evidence", "reconciliation", "explanation",
    }
    _reject_extra_fields(bundle, completion_fields, "completion bundle")
    _require_present_fields(bundle, tuple(completion_fields), "completion bundle")
    if bundle["schema_version"] != 1 or bundle["run_id"] != run_id:
        raise ValueError("completion bundle schema or run binding is invalid")
    if not isinstance(bundle["implementation_notes"], dict) or not bundle["implementation_notes"]:
        raise ValueError("implementation_notes must be a non-empty object")
    if not isinstance(bundle["explanation"], dict):
        raise ValueError("explanation must be an object")
    _reject_extra_fields(bundle["explanation"], {"change_explanation", "risks", "rollback", "comprehension_evidence"}, "explanation")
    _require_fields(bundle["explanation"], ("change_explanation", "risks", "rollback", "comprehension_evidence"), "explanation")
    for field in ("change_explanation", "rollback", "comprehension_evidence"):
        if not isinstance(bundle["explanation"][field], str) or not bundle["explanation"][field].strip():
            raise ValueError(f"explanation {field} must be a non-empty string")
    risks = bundle["explanation"]["risks"]
    if not isinstance(risks, list) or not risks or not all(isinstance(item, str) and item.strip() for item in risks):
        raise ValueError("explanation risks must be a non-empty string array")
    plan_only = approval_material["task_profile"] == "plan_only"
    mutation_expected = not plan_only and not (approval_material["task_profile"] == "debug" and not approval_material["scope"]["paths"])
    _validate_increment_evidence(approval_material["plan"], bundle["increment_evidence"], plan_only=plan_only)
    _validate_acceptance_evidence(approval_material["acceptance"], bundle["acceptance_evidence"])
    _validate_durable_attempts(state, approval_material["plan"], approval_bundle_hash, plan_only=plan_only)
    verification_view = {
        "schema_version": bundle["schema_version"],
        "run_id": bundle["run_id"],
        "approval_bundle_hash": approval_bundle_hash,
        "implementation_notes": bundle["implementation_notes"],
        "increment_evidence": bundle["increment_evidence"],
        "acceptance_evidence": bundle["acceptance_evidence"],
        "reconciliation": bundle["reconciliation"],
    }
    pending = state.get("evidence", {}).get("pending_verification_packet")
    if not isinstance(pending, dict):
        raise ValueError("no hook-sealed verification packet exists")
    if pending.get("active") is not True or pending.get("reviewed") is not True or pending.get("review_result") != "PASS":
        raise ValueError("the latest sealed verification packet has no accepted terminal PASS")
    if digest(verification_view) != digest(pending.get("submitted_packet")):
        raise ValueError("completion bundle differs from the submitted verification material")
    packet_hash = pending.get("hash")
    if bundle["verification_packet_hash"] != packet_hash:
        raise ValueError("completion bundle does not match the latest hook-sealed verification_packet_hash")
    verifier = state.get("evidence", {}).get("accepted_verifier")
    if not isinstance(verifier, dict) or not verifier.get("fresh_start_matched"):
        raise ValueError("no matching fresh-context verifier receipt was observed")
    if verifier.get("packet_hash") != packet_hash:
        raise ValueError("verifier receipt belongs to a different verification packet")
    if verifier.get("packet_hash_at_start") != packet_hash:
        raise ValueError("the exact sealed verification packet was not injected at verifier start")
    receipt = _validate_verifier_receipt(
        str(verifier.get("output", "")),
        packet_hash,
        approval_material["acceptance"],
    )
    verifier = {**verifier, "receipt": receipt}
    current_fingerprint = compute_base_fingerprint(project)
    if pending["packet"]["reconciliation"]["final_fingerprint"] != current_fingerprint:
        raise ValueError("hook-owned completion final_fingerprint does not match the current project")
    if pending.get("project_fingerprint") != current_fingerprint or verifier.get("project_fingerprint") != current_fingerprint:
        raise ValueError("project changed after the verification packet was sealed; run a new verifier")
    inventory, current_manifest, content_delta = _validate_actual_changes(
        project,
        approval_material,
        mutation_expected=mutation_expected,
    )
    _validate_reconciliation(
        bundle["reconciliation"],
        plan=approval_material["plan"],
        criteria=approval_material["acceptance"],
        scope=approval_material["scope"],
        actual_paths=[item["path"] for item in inventory],
    )
    if inventory != pending["packet"].get("changed_inventory"):
        raise ValueError("hook-derived changed inventory differs from the verifier packet")
    if content_delta != pending["packet"].get("content_delta"):
        raise ValueError("hook-derived content delta differs from the verifier packet")
    if digest(current_manifest) != pending["packet"].get("final_manifest_hash"):
        raise ValueError("project manifest changed after verifier sealing")
    return verifier

def _ingest_completion_bundle(
    store: RuntimeStore,
    state: dict[str, Any],
    *,
    session_id: str,
    run_id: str,
    authority: AuthorityStore,
    bundle: dict[str, Any],
    project: Path,
) -> dict[str, Any]:
    if state["phase"] != Phase.IMPLEMENTATION_LOOP.value:
        raise ValueError("completion bundle is accepted only during IMPLEMENTATION_LOOP")
    raw = _raw_material(state)
    material = _material(raw)
    valid, reasons, _ = authority.validate(
        run_id=run_id,
        session_id=session_id,
        project=store.identity,
        material=material,
    )
    if not valid:
        raise ValueError("current approval is invalid: " + "; ".join(reasons))
    verifier = _validated_completion_bundle(
        bundle,
        run_id=run_id,
        state=state,
        project=project,
        approval_material=raw,
        approval_bundle_hash=material["bundle_hash"],
    )
    sealed_reconciliation = state["evidence"]["pending_verification_packet"]["packet"]["reconciliation"]
    operations: list[dict[str, Any]] = [
        {"operation": "record_evidence", "kind": "implementation_notes", "value": bundle["implementation_notes"]},
        {"operation": "record_evidence", "kind": "acceptance_evidence", "value": bundle["acceptance_evidence"]},
        {"operation": "record_evidence", "kind": "independent_verification", "value": verifier},
        {"operation": "record_evidence", "kind": "verification_packet_receipt", "value": {"hash": bundle["verification_packet_hash"], "verifier_output_hash": verifier["output_hash"]}},
        {"operation": "record_evidence", "kind": "plan_vs_actual_reconciliation", "value": sealed_reconciliation},
        {"operation": "record_evidence", "kind": "explanation_and_comprehension", "value": bundle["explanation"]},
    ]
    if state["task_profile"] == "plan_only":
        operations.append({
            "operation": "transition",
            "to_phase": Phase.INDEPENDENT_VERIFICATION.value,
            "outcome": PhaseStatus.NOT_APPLICABLE.value,
            "reason": "The approved plan-only run performed no implementation mutation",
            "not_applicable_code": "plan_only_no_mutation",
            "evidence": {"approved_plan": material["bundle_hash"], "no_mutation_performed": "confirmed"},
        })
    else:
        operations.append({"operation": "transition", "to_phase": Phase.INDEPENDENT_VERIFICATION.value, "evidence": {"increments": bundle["increment_evidence"]}})
    operations.extend([
        {"operation": "transition", "to_phase": Phase.PLAN_VS_ACTUAL_RECONCILIATION.value, "evidence": {"verifier": verifier["output_hash"]}},
        {"operation": "transition", "to_phase": Phase.EXPLANATION_AND_COMPREHENSION_CHECK.value, "evidence": sealed_reconciliation},
        {"operation": "transition", "to_phase": Phase.DONE.value, "evidence": bundle["explanation"]},
    ])
    state = store.apply_batch(session_id=session_id, operations=operations)
    authority.invalidate(["run completed; approval receipt consumed"])
    return state

def _ingest_attempt_packet(
    store: RuntimeStore,
    state: dict[str, Any],
    *,
    session_id: str,
    run_id: str,
    authority: AuthorityStore,
    project: Path,
    packet: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    fields = {
        "schema_version", "run_id", "approval_bundle_hash", "step", "hypothesis",
        "action", "evidence_snapshot", "outcome", "evidence_gain",
    }
    _reject_extra_fields(packet, fields, "attempt packet")
    _require_present_fields(packet, tuple(fields), "attempt packet")
    if packet["schema_version"] != 1 or packet["run_id"] != run_id:
        raise ValueError("attempt packet schema or run binding is invalid")
    if state["phase"] != Phase.IMPLEMENTATION_LOOP.value or state.get("terminal_state") is not None:
        raise ValueError("attempt packets are accepted only during an active IMPLEMENTATION_LOOP")
    raw = _raw_material(state)
    if raw["task_profile"] == "plan_only":
        raise ValueError("plan_only runs must not manufacture implementation attempts")
    pending = state.get("evidence", {}).get("pending_attempt", {})
    if pending.get("active") is not True:
        raise ValueError("attempt packet has no matching pending substantive act")
    material = _material(raw)
    if packet["approval_bundle_hash"] != material["bundle_hash"]:
        raise ValueError("attempt packet belongs to another approval bundle")
    if pending.get("approval_bundle_hash") != material["bundle_hash"]:
        raise ValueError("pending substantive act belongs to another approval bundle")
    valid, reasons, _ = authority.validate(
        run_id=run_id,
        session_id=session_id,
        project=store.identity,
        material=material,
    )
    # A hook-authorized act may always be closed for audit, even if a later human
    # message invalidated its approval. No further substantive act will be allowed.
    expected_steps = {step["id"] for step in raw["plan"]}
    for field in ("step", "hypothesis", "action", "evidence_snapshot"):
        if not isinstance(packet[field], str) or not packet[field].strip():
            raise ValueError(f"attempt {field} must be a non-empty string")
    if packet["step"] not in expected_steps:
        raise ValueError("attempt packet names an unknown approved plan step")
    if packet["outcome"] not in {"PASS", "FAIL"} or not isinstance(packet["evidence_gain"], bool):
        raise ValueError("attempt outcome must be PASS or FAIL and evidence_gain must be boolean")
    if packet["outcome"] == "PASS" and packet["evidence_gain"] is not True:
        raise ValueError("a passing attempt must record evidence gain")
    unapproved, inventory, current_manifest, _ = _unapproved_changed_paths(project, raw)
    state = store.record_attempt(
        session_id=session_id,
        approval_bundle_hash=material["bundle_hash"],
        step=packet["step"],
        hypothesis=packet["hypothesis"],
        action=packet["action"],
        evidence_snapshot=packet["evidence_snapshot"],
        project_fingerprint=digest(current_manifest),
        authority_valid_at_close=valid,
        authority_invalid_reasons=reasons,
        scope_valid_at_close=not unapproved,
        unapproved_paths=unapproved,
        failed=packet["outcome"] == "FAIL",
        evidence_gain=packet["evidence_gain"],
    )
    if unapproved:
        reason = "The hook-observed act produced content outside approved mutation paths"
        authority.invalidate([reason])
        state = store.apply_batch(
            session_id=session_id,
            operations=[
                {
                    "operation": "record_evidence",
                    "kind": "scope_violation",
                    "value": {
                        "reason": reason,
                        "unapproved_paths": unapproved,
                        "changed_inventory": inventory,
                        "attempt_fingerprint": state["attempts"][-1]["fingerprint"],
                        "required_action": "Revert the unapproved delta before sealing or approving any new baseline",
                    },
                },
                {
                    "operation": "transition",
                    "to_phase": Phase.UNKNOWNS_AND_BLINDSPOTS.value,
                    "reason": "An unapproved act delta requires phase-3 re-entry and cannot become a new baseline",
                    "evidence": {"unapproved_paths": unapproved},
                },
            ],
        )
        return state, "scope_violation"
    if state["must_stop"]:
        reason = "Three consecutive failed implementation attempts produced no evidence gain"
        authority.invalidate([reason])
        state = store.record_evidence(
            session_id=session_id,
            kind="loop_stop",
            value={
                "reason": reason,
                "attempt": packet,
                "consecutive_no_gain_failures": state["repeated_no_gain_failures"],
                "required_next_action": "Present a bounded A-D human decision packet or an explicit terminal packet",
            },
        )
        return state, "three_no_gain"
    return state, None


def _ingest_terminal_packet(
    store: RuntimeStore,
    state: dict[str, Any],
    *,
    session_id: str,
    run_id: str,
    packet: dict[str, Any],
) -> dict[str, Any]:
    fields = {"schema_version", "run_id", "terminal_state", "current_phase", "reason", "evidence", "resume_condition"}
    _reject_extra_fields(packet, fields, "terminal packet")
    _require_fields(packet, tuple(fields), "terminal packet")
    if packet["schema_version"] != 1 or packet["run_id"] != run_id:
        raise ValueError("terminal packet schema or run binding is invalid")
    if packet["terminal_state"] not in {TerminalState.BLOCKED.value, TerminalState.NEEDS_HUMAN_JUDGMENT.value}:
        raise ValueError("terminal packet state must be BLOCKED or NEEDS_HUMAN_JUDGMENT")
    if packet["current_phase"] != state["phase"]:
        raise ValueError("terminal packet current_phase does not match hook state")
    if not isinstance(packet["reason"], str) or not packet["reason"].strip():
        raise ValueError("terminal packet reason must be a non-empty string")
    if not isinstance(packet["evidence"], dict) or not packet["evidence"]:
        raise ValueError("terminal packet evidence must be a non-empty object")
    if not isinstance(packet["resume_condition"], str) or not packet["resume_condition"].strip():
        raise ValueError("terminal packet resume_condition must be a non-empty string")
    return store.set_terminal(
        session_id=session_id,
        terminal_state=packet["terminal_state"],
        reason=packet["reason"],
        evidence=packet["evidence"],
        resume_condition=packet["resume_condition"],
    )


def handle_hook(*, host: str, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    if host not in {"codex", "claude"} or event not in SUPPORTED_EVENTS:
        return _result(Decision.NEEDS_HUMAN_JUDGMENT, "Unsupported host or event; coverage is not claimed", host=host, event=event)
    session_id = str(payload.get("session_id") or os.environ.get("MYTHOS_SESSION_ID") or "")
    invocation_path = Path(payload.get("cwd") or payload.get("project_root") or os.getcwd()).resolve(strict=False)
    identity = project_identity(invocation_path)
    project = Path(str(identity["project_root"])).resolve(strict=False)
    if not session_id:
        return _result(Decision.NEEDS_HUMAN_JUDGMENT, "The host did not expose a session identifier", host=host, event=event)
    run_id = _run_id(payload, project, session_id)
    state_root = _root(payload)
    if state_root is not None:
        try:
            if os.path.normcase(os.path.commonpath([str(state_root), str(project)])) == os.path.normcase(str(project)):
                return _result(
                    Decision.NEEDS_HUMAN_JUDGMENT,
                    "MYTHOS5_STATE_HOME must be outside the governed project so state writes cannot churn approval fingerprints",
                    host=host,
                    event=event,
                )
        except ValueError:
            pass
    store = RuntimeStore(project, run_id, root=state_root)
    if event == "SessionStart":
        state = store.initialize(session_id=session_id, task_profile="build")
        context = (
            f"Mythos 5 Burning Art is active. Run ID: {run_id}. Current phase: {state['phase']}. "
            "For substantive coding work, invoke $mythos-orchestrate and complete all thirteen phases. "
            "Do not mutate before the hook-owned human approval receipt."
        )
        return _result(Decision.ALLOW, "Mythos run initialized", host=host, event=event, context=context)
    try:
        state = store.load()
    except Exception as error:
        return _result(Decision.NEEDS_HUMAN_JUDGMENT, f"Run state is unavailable: {error}", host=host, event=event)
    authority = AuthorityStore(store.paths)

    if event == "UserPromptSubmit":
        message = str(payload.get("prompt", payload.get("message", "")))
        terminal = state.get("terminal_state")
        resumed_from_waiting = terminal == TerminalState.AWAITING_HUMAN_INPUT.value
        if terminal == TerminalState.AWAITING_HUMAN_INPUT.value:
            state = store.resume(session_id=session_id)
            state = store.record_evidence(
                session_id=session_id,
                kind="human_resume_observation",
                value={"request": _request_record(payload, message), "prior_terminal_state": terminal},
            )
        elif terminal in {
            TerminalState.NEEDS_HUMAN_JUDGMENT.value,
            TerminalState.BLOCKED.value,
            TerminalState.VERIFICATION_FAILED.value,
        }:
            prefix = f"RESUME MYTHOS RUN {run_id}:"
            if not message.startswith(prefix) or not message[len(prefix):].strip():
                return _result(
                    Decision.ALLOW,
                    f"Run remains in explicit terminal state {terminal}",
                    host=host,
                    event=event,
                    context=(
                        f"Do not continue or mutate. The recorded reason is: {state.get('terminal_reason')}. "
                        f"The recorded resume condition is: {state.get('resume_condition')}. "
                        f"To acknowledge resolution explicitly, send `{prefix} <what changed or what evidence is now available>`."
                    ),
                )
            state = store.resume(session_id=session_id)
            state = store.record_evidence(
                session_id=session_id,
                kind="human_resume_observation",
                value={"request": _request_record(payload, message), "prior_terminal_state": terminal},
            )

        try:
            raw = _raw_material(state)
            material = _material(raw)
            expected = approval_syntax(run_id, material["bundle_hash"])
        except ValueError:
            expected = None
        if expected and message == expected:
            if state["phase"] != Phase.AWAITING_HUMAN_PLAN_APPROVAL.value:
                return _result(Decision.DENY, "Approval arrived outside AWAITING_HUMAN_PLAN_APPROVAL", host=host, event=event)
            if state.get("terminal_state") != TerminalState.AWAITING_HUMAN_PLAN_APPROVAL.value:
                return _result(Decision.DENY, "The exact plan is no longer in its hook-owned approval wait", host=host, event=event)
            if state.get("evidence", {}).get("pending_plan_feedback", {}).get("status") == "pending":
                return _result(Decision.DENY, "Plan feedback requires a newly sealed plan and critic before approval", host=host, event=event)
            if raw["base_fingerprint"] != compute_base_fingerprint(project):
                return _result(Decision.DENY, "Project base changed after planning; re-plan before approval", host=host, event=event)
            current_scope_fingerprint = _scope_fingerprint(project, raw["scope"])
            if raw.get("base_scope_fingerprint") != current_scope_fingerprint:
                return _result(Decision.DENY, "Approved scope changed after planning; re-plan before approval", host=host, event=event)
            state = store.resume(session_id=session_id)
            observation = observe_human_event(host=host, event_name=event, payload=payload)
            document = authority.create(
                observation=observation,
                run_id=run_id,
                project=store.identity,
                material=material,
                scope=raw["scope"],
            )
            state = store.apply_batch(
                session_id=session_id,
                operations=[
                    {
                        "operation": "transition",
                        "to_phase": Phase.IMPLEMENTATION_LOOP.value,
                        "approval_valid": True,
                        "evidence": {"approval_receipt_hash": digest(document["receipt"])},
                    },
                    {
                        "operation": "record_evidence",
                        "kind": "pending_verification_packet",
                        "value": {"active": False, "reason": "cleared by a new exact human approval"},
                    },
                ],
            )
            return _result(
                Decision.ALLOW,
                "Exact human approval recorded",
                host=host,
                event=event,
                context=f"Run {run_id} is approved for only the bound scope. Enter IMPLEMENTATION_LOOP and invoke the profile-specific execution skill.",
            )
        if terminal == TerminalState.AWAITING_HUMAN_PLAN_APPROVAL.value:
            state = store.resume(session_id=session_id)
            authority.invalidate(["human plan feedback requires a new sealed review packet"])
            request = _request_record(payload, message)
            state = store.record_evidence(
                session_id=session_id,
                kind="pending_plan_feedback",
                value={"status": "pending", "request": request},
            )
            state = store.record_evidence(session_id=session_id, kind="latest_human_instruction", value=request)
            return _result(
                Decision.ALLOW,
                "Plan feedback recorded; prior approval candidate invalidated",
                host=host,
                event=event,
                context="Do not mutate. Re-enter phase 3, seal a new review packet, run a new independent critic, and request approval for the revised exact plan.",
            )
        if state["phase"] == Phase.DONE.value:
            return _result(
                Decision.ALLOW,
                "Completed run is immutable",
                host=host,
                event=event,
                context="This run is DONE and its approval was consumed. Use a new host task/session for new substantive work; no mutation is authorized here.",
            )

        read_only = _read_only_exempt(message)
        if state["phase"] == Phase.INTAKE.value and not state["phase_records"]:
            if read_only:
                state = store.record_evidence(
                    session_id=session_id,
                    kind="read_only_exempt",
                    value={"active": True, "request_hash": digest(message), "reason": "Pure answer or explanation with no requested side effect"},
                )
                return _result(Decision.ALLOW, "Read-only exemption recorded", host=host, event=event, context="This prompt is read-only exempt. Do not mutate files, Git, dependencies, or external systems.")
            if state.get("evidence", {}).get("read_only_exempt", {}).get("active"):
                state = store.record_evidence(
                    session_id=session_id,
                    kind="read_only_exempt",
                    value={"active": False, "request_hash": digest(message), "reason": "Current prompt is substantive"},
                )
            request = _request_record(payload, message)
            if "original_request" not in state.get("evidence", {}):
                state = store.record_evidence(session_id=session_id, kind="original_request", value=request)
            state = store.record_evidence(session_id=session_id, kind="latest_human_instruction", value=request)
            profile = _task_profile(message)
            if state["task_profile"] != profile:
                state = store.set_task_profile(session_id=session_id, task_profile=profile)

        if state["phase"] == Phase.IMPLEMENTATION_LOOP.value:
            continuation = re.fullmatch(r"\s*(?:continue|resume|proceed(?: with the approved plan)?)\.?\s*", message, re.IGNORECASE)
            if (continuation or read_only) and not resumed_from_waiting:
                return _result(
                    Decision.ALLOW,
                    "Approved run continuation observed",
                    host=host,
                    event=event,
                    context="Continue only the existing approved plan. This message does not expand scope or authorize another task.",
                )
            request = _request_record(payload, message)
            authority.invalidate(["a new human message may change the approved implementation"])
            state = store.record_evidence(session_id=session_id, kind="latest_human_instruction", value=request)
            state = store.record_evidence(
                session_id=session_id,
                kind="post_approval_human_message",
                value={"request_hash": digest(message), "disposition": "approval invalidated; replan required"},
            )
            return _result(
                Decision.ALLOW,
                "Approval invalidated by new substantive human input",
                host=host,
                event=event,
                context="Do not mutate. Reconcile this message with the goal, seal a new MYTHOS_REVIEW_PACKET_V1 from phase 3, run a new critic, and obtain a new human approval.",
            )
        if not read_only:
            state = store.record_evidence(session_id=session_id, kind="latest_human_instruction", value=_request_record(payload, message))
        if state["phase"] == Phase.AWAITING_HUMAN_PLAN_APPROVAL.value:
            context = (
                "The current plan is not approved. Treat this human message as review feedback. If it changes material, "
                "seal a new review packet from phase 3, run a new fresh-context critic, and emit a new approval bundle. Do not mutate."
            )
        else:
            context = f"Route this substantive request through $mythos-orchestrate. Run ID: {run_id}. Current phase: {state['phase']}."
        return _result(Decision.ALLOW, "Human prompt observed", host=host, event=event, context=context)
    if event in {"SubagentStart", "SubagentStop"}:
        role = _agent_role(payload)
        if role is not None:
            allowed, gate_reason = _agent_start_gate(state, role)
            if not allowed:
                return _result(Decision.DENY, f"Independent reviewer event rejected: {gate_reason}", host=host, event=event)
        state = _record_agent_event(store, state, session_id=session_id, event=event, payload=payload, project=project, host=host)
        context = None
        if event == "SubagentStart" and role:
            active = state["evidence"][f"active_{role}"]
            packet_label = "Review" if role == "plan_critic" else "Verification"
            packet_hash = active.get("packet_hash") or "MISSING"
            fingerprint_note = ""
            if role == "verifier":
                fingerprint_note = f" The project fingerprint at verifier start is {active['project_fingerprint']}."
            sealed_packet = active.get("packet")
            sealed_text = canonical_text(sealed_packet) if isinstance(sealed_packet, dict) else "MISSING\n"
            isolation_note = (
                " Host-observed context isolation is verified."
                if active.get("isolation_verified") is True
                else " Host-observed context isolation is NOT verified; do not issue PASS. Return REVIEW_INVALID or VERIFICATION_INVALID."
            )
            receipt_marker = "MYTHOS_CRITIC_RECEIPT_V1" if role == "plan_critic" else "MYTHOS_VERIFIER_RECEIPT_V1"
            context = (
                "Operate as a fresh-context, read-only Mythos reviewer. Do not implement, repair, invoke another agent, "
                f"or accept hidden reasoning. {packet_label} packet hash: {packet_hash}. "
                "Review only the complete sealed packet printed below. A PASS requires exactly one textual Verdict: PASS "
                f"and exactly one strict JSON {receipt_marker}_BEGIN/END block bound to this hash; any blocking, high-severity, "
                "or context-contamination finding requires a non-PASS verdict."
                + isolation_note
                + fingerprint_note
                + "\nSealed packet JSON:\n"
                + sealed_text
            )
        if event == "SubagentStop" and role:
            state, accepted, outcome = _adjudicate_agent_stop(
                store,
                state,
                session_id=session_id,
                role=role,
                project=project,
                authority=authority,
            )
            if not accepted:
                route = (
                    "Approval invalidated and lifecycle moved to phase 3 UNKNOWNS_AND_BLINDSPOTS. "
                    "Seal a new review packet, use a fresh critic, and obtain new human approval."
                    if role == "verifier"
                    else "The sealed plan review is rejected. Revise the plan and seal a new review packet before launching another critic."
                )
                return _result(Decision.DENY, f"Independent {role.replace('_', ' ')} non-PASS: {outcome}", host=host, event=event, context=route)
            return _result(Decision.ALLOW, f"Independent {role.replace('_', ' ')} PASS accepted and sealed", host=host, event=event)
        return _result(Decision.ALLOW, "Observable subagent lifecycle event recorded", host=host, event=event, context=context)
    if event == "Stop":
        message = str(payload.get("last_assistant_message") or payload.get("message") or "")
        if state.get("terminal_state") in {
            TerminalState.BLOCKED.value,
            TerminalState.NEEDS_HUMAN_JUDGMENT.value,
            TerminalState.AWAITING_HUMAN_INPUT.value,
            TerminalState.AWAITING_HUMAN_PLAN_APPROVAL.value,
            TerminalState.VERIFICATION_FAILED.value,
        }:
            resume = state.get("resume_condition") or "A human resolves the recorded blocker or supplies the required decision."
            return _result(
                Decision.ALLOW,
                f"Run stopped in explicit terminal state {state['terminal_state']}",
                host=host,
                event=event,
                system_message=(
                    f"{state.get('terminal_reason') or 'Mythos requires human input or an external-state change.'} "
                    f"Resume condition: {resume}"
                ),
            )
        if state["phase"] == Phase.DONE.value:
            authority.invalidate(["run is DONE; approval cannot be reused"])
            failures = done_guard_failures(state)
            if failures:
                return _result(Decision.DENY, "DONE guard failed: " + "; ".join(failures), host=host, event=event)
            return _result(Decision.ALLOW, "DONE guard passed", host=host, event=event)
        if state.get("evidence", {}).get("read_only_exempt", {}).get("active") and state["phase"] == Phase.INTAKE.value:
            return _result(Decision.ALLOW, "Read-only exempt response may stop", host=host, event=event)
        try:
            packets = {
                "terminal": _extract_json(message, TERMINAL_BEGIN, TERMINAL_END),
                "attempt": _extract_json(message, ATTEMPT_BEGIN, ATTEMPT_END),
                "review": _extract_json(message, REVIEW_BEGIN, REVIEW_END),
                "approval": _extract_json(message, PLAN_BEGIN, PLAN_END),
                "verification": _extract_json(message, VERIFICATION_BEGIN, VERIFICATION_END),
                "completion": _extract_json(message, COMPLETION_BEGIN, COMPLETION_END),
            }
            present = [kind for kind, packet in packets.items() if packet is not None]
            if len(present) > 1:
                raise ValueError("a Stop response may contain exactly one Mythos protocol packet")
            terminal_packet = packets["terminal"]
            attempt_packet = packets["attempt"]
            review_packet = packets["review"]
            plan_bundle = packets["approval"]
            verification_packet = packets["verification"]
            completion_bundle = packets["completion"]
            if terminal_packet is not None:
                state = _ingest_terminal_packet(
                    store,
                    state,
                    session_id=session_id,
                    run_id=run_id,
                    packet=terminal_packet,
                )
                authority.invalidate([f"run entered {state['terminal_state']}: {state['terminal_reason']}"])
                return _result(
                    Decision.ALLOW,
                    f"Explicit terminal packet accepted: {state['terminal_state']}",
                    host=host,
                    event=event,
                    system_message=(
                        f"{state['terminal_reason']} Resume condition: {state['resume_condition']}. "
                        f"To resume after resolution, send `RESUME MYTHOS RUN {run_id}: <what changed or what evidence is now available>`."
                    ),
                )
            if attempt_packet is not None:
                state, stop_reason = _ingest_attempt_packet(
                    store,
                    state,
                    session_id=session_id,
                    run_id=run_id,
                    authority=authority,
                    project=project,
                    packet=attempt_packet,
                )
                if stop_reason == "scope_violation":
                    return _result(
                        Decision.DENY,
                        "Attempt recorded for audit, but its hook-observed delta exceeded approved paths. Approval is invalid, lifecycle is at phase 3, and the unapproved delta must be reverted before any new review or baseline.",
                        host=host,
                        event=event,
                    )
                if stop_reason == "three_no_gain":
                    return _result(
                        Decision.DENY,
                        "Three consecutive no-gain failures reached the hard stop. Do not use another tool or repeat a failed fingerprint. Present one to five exact numbered A-D questions with MYTHOS_WAITING_FOR_HUMAN_V1, or emit MYTHOS_TERMINAL_PACKET_V1 with concrete evidence and a resume condition.",
                        host=host,
                        event=event,
                    )
                return _result(
                    Decision.DENY,
                    "Durable implementation attempt recorded. Continue the approved loop or prepare verification when every plan step has a passing evidence-gain attempt.",
                    host=host,
                    event=event,
                )
            if review_packet is not None:
                state, packet_hash = _ingest_review_packet(
                    store,
                    state,
                    session_id=session_id,
                    run_id=run_id,
                    project=project,
                    authority=authority,
                    packet=review_packet,
                )
                return _result(
                    Decision.DENY,
                    f"Review packet sealed as {packet_hash}. Launch a fresh mythos-plan-critic; the hook will inject the complete sealed packet. Require exactly one verdict and one strict MYTHOS_CRITIC_RECEIPT_V1 block bound to this hash before emitting the approval bundle.",
                    host=host,
                    event=event,
                )
            if plan_bundle is not None:
                state, expected = _ingest_plan_bundle(
                    store,
                    state,
                    session_id=session_id,
                    run_id=run_id,
                    project=project,
                    authority=authority,
                    bundle=plan_bundle,
                )
                notice = f"Plan review gate active. To approve this exact bundle, send: {expected}"
                return _result(Decision.ALLOW, "Awaiting human plan approval", host=host, event=event, system_message=notice)
            if verification_packet is not None:
                state, packet_hash = _ingest_verification_packet(
                    store,
                    state,
                    session_id=session_id,
                    run_id=run_id,
                    project=project,
                    authority=authority,
                    packet=verification_packet,
                )
                return _result(
                    Decision.DENY,
                    f"Verification packet sealed as {packet_hash}. Launch a fresh mythos-verifier; the hook will inject the complete sealed packet. Require exactly one verdict and one strict MYTHOS_VERIFIER_RECEIPT_V1 block bound to this hash before completion.",
                    host=host,
                    event=event,
                )
            if completion_bundle is not None:
                state = _ingest_completion_bundle(
                    store,
                    state,
                    session_id=session_id,
                    run_id=run_id,
                    authority=authority,
                    bundle=completion_bundle,
                    project=project,
                )
                return _result(Decision.ALLOW, "Completion bundle accepted and DONE guard passed", host=host, event=event)
        except Exception as error:
            return _result(Decision.DENY, f"Mythos bundle rejected: {error}", host=host, event=event)
        if state["phase"] == Phase.AWAITING_HUMAN_PLAN_APPROVAL.value:
            raw = _raw_material(state)
            expected = approval_syntax(run_id, _material(raw)["bundle_hash"])
            return _result(
                Decision.ALLOW,
                "Waiting for explicit human approval",
                host=host,
                event=event,
                system_message=f"Plan review gate active. To approve this exact bundle, send: {expected}",
            )
        if WAITING_MARKER in message:
            if state.get("evidence", {}).get("pending_attempt", {}).get("active") is True:
                return _result(Decision.DENY, "Close the pending substantive act with an exact attempt packet before asking the human", host=host, event=event)
            if not _has_decision_packet(message):
                return _result(Decision.DENY, "Waiting marker requires the exact one-to-five-question A-D decision grammar", host=host, event=event)
            if state["phase"] == Phase.IMPLEMENTATION_LOOP.value:
                authority.invalidate(["a consequential human decision is unresolved"])
            state = store.set_terminal(
                session_id=session_id,
                terminal_state=TerminalState.AWAITING_HUMAN_INPUT,
                reason="A consequential A-D decision packet was presented",
                evidence={"decision_packet_hash": digest(message)},
                resume_condition="The human answers the numbered A-D question packet",
            )
            return _result(Decision.ALLOW, "Waiting for consequential human input", host=host, event=event, system_message="Mythos is waiting for the numbered A-D decision packet above.")
        return _result(
            Decision.DENY,
            "Stop blocked: emit the required attempt, review, approval, verification, completion, or terminal packet for the current phase, or present a valid A-D packet with MYTHOS_WAITING_FOR_HUMAN_V1",
            host=host,
            event=event,
        )
    tool_name = str(payload.get("tool_name") or payload.get("tool") or "")
    tool_input = payload.get("tool_input") or payload.get("arguments") or {}
    if not isinstance(tool_input, dict):
        return _result(Decision.DENY, "Tool input must be an object", host=host, event=event)
    if event == "PreToolUse":
        state, launch_role, launch_error = _record_reviewer_launch(
            store,
            state,
            session_id=session_id,
            host=host,
            tool_name=tool_name,
            tool_input=tool_input,
            project=project,
        )
        if launch_error is not None:
            return _result(
                Decision.DENY,
                f"Independent {launch_role.replace('_', ' ') if launch_role else 'reviewer'} launch rejected: {launch_error}",
                host=host,
                event=event,
            )
    classification = classify_tool(tool_name, tool_input)
    pending = state.get("evidence", {}).get("pending_attempt", {})
    if event == "PermissionRequest":
        if pending.get("active") is True:
            request_tool_use_id = _tool_use_id(payload)
            pending_tool_use_id = pending.get("tool_use_id")
            matches = (
                pending.get("tool_name") == tool_name
                and pending.get("tool_input_hash") == digest(tool_input)
                and pending_tool_use_id == request_tool_use_id
            )
            if not matches:
                return _result(
                    Decision.DENY,
                    "PermissionRequest does not match the active PreToolUse act by tool name, exact input hash, and tool-use ID",
                    host=host,
                    event=event,
                )
            try:
                raw = _raw_material(state)
                material = _material(raw)
            except ValueError as error:
                return _result(Decision.DENY, f"PermissionRequest act binding is unavailable: {error}", host=host, event=event)
            valid, reasons, receipt = authority.validate(
                run_id=run_id,
                session_id=session_id,
                project=store.identity,
                material=material,
            )
            if not valid or pending.get("approval_bundle_hash") != material["bundle_hash"]:
                if receipt is not None:
                    authority.invalidate(reasons or ["the pending act no longer matches the approved bundle"])
                return _result(
                    Decision.DENY,
                    "PermissionRequest act no longer has current Mythos approval: " + "; ".join(reasons or ["bundle mismatch"]),
                    host=host,
                    event=event,
                )
            if _scope_fingerprint(project, raw["scope"]) != pending.get("project_fingerprint_before"):
                authority.invalidate(["project content changed between PreToolUse and PermissionRequest"])
                return _result(
                    Decision.DENY,
                    "Project content changed between PreToolUse and PermissionRequest; replan and reapprove",
                    host=host,
                    event=event,
                )
            observed = {
                **pending,
                "permission_request_observed": True,
                "permission_request_count": int(pending.get("permission_request_count", 0)) + 1,
            }
            store.record_evidence(session_id=session_id, kind="pending_attempt", value=observed)
            return _result(
                Decision.ALLOW,
                "PermissionRequest matches the active PreToolUse act; native host permission remains authoritative",
                host=host,
                event=event,
            )
        if classification.decision is not Decision.ALLOW:
            return _result(
                Decision.DENY,
                "Substantive PermissionRequest has no matching hook-recorded PreToolUse act",
                host=host,
                event=event,
            )
    if classification.decision is Decision.ALLOW:
        guarded_read = approved_tool_guard(
            tool_name=tool_name,
            tool_input=tool_input,
            project_root=project,
            scope={"paths": [], "commands": [], "external_effects": []},
            invocation_root=invocation_path,
        )
        return _result(guarded_read.decision, guarded_read.reason, host=host, event=event)
    if state["phase"] != Phase.IMPLEMENTATION_LOOP.value or state.get("terminal_state") is not None:
        return _result(
            Decision.DENY,
            "Mutation is permitted only during an active IMPLEMENTATION_LOOP with a current approval",
            host=host,
            event=event,
        )
    if state.get("evidence", {}).get("pending_verification_packet", {}).get("active") is True:
        return _result(Decision.DENY, "Mutation denied because the hook-owned verification snapshot is frozen; re-plan and reapprove before repair", host=host, event=event)
    if state.get("must_stop"):
        return _result(Decision.DENY, "Mutation denied by the three-consecutive-no-gain hard stop; ask the human or enter an explicit terminal state", host=host, event=event)
    if state.get("task_profile") == "plan_only":
        return _result(Decision.DENY, "PLAN_ONLY runs never authorize mutation", host=host, event=event)
    if state.get("evidence", {}).get("pending_attempt", {}).get("active") is True:
        return _result(
            Decision.DENY,
            "The prior substantive act must be closed by one exact MYTHOS_ATTEMPT_PACKET_V1 before another substantive act",
            host=host,
            event=event,
        )
    try:
        raw = _raw_material(state)
        material = _material(raw)
    except ValueError:
        return _result(
            Decision.DENY,
            "No hook-owned approval-ready plan exists; use read-only discovery, planning, questions, or a fresh reviewer",
            host=host,
            event=event,
        )
    valid, reasons, receipt = authority.validate(
        run_id=run_id,
        session_id=session_id,
        project=store.identity,
        material=material,
    )
    if not valid:
        if receipt is not None:
            authority.invalidate(reasons)
        return _result(Decision.DENY, "Approval invalid: " + "; ".join(reasons), host=host, event=event)
    bound_attempts = [
        item for item in state.get("attempts", [])
        if item.get("approval_bundle_hash") == material["bundle_hash"]
    ]
    expected_fingerprint = (
        bound_attempts[-1].get("project_fingerprint") if bound_attempts
        else raw["base_scope_fingerprint"]
    )
    current_fingerprint = _scope_fingerprint(project, raw["scope"])
    if not expected_fingerprint or current_fingerprint != expected_fingerprint:
        authority.invalidate(["project content changed outside the recorded attempt boundary"])
        return _result(
            Decision.DENY,
            "Approval invalid: project content changed outside the recorded attempt boundary; re-enter phase 3 and obtain a new approval",
            host=host,
            event=event,
        )
    guarded = approved_tool_guard(
        tool_name=tool_name,
        tool_input=tool_input,
        project_root=project,
        scope=receipt["scope"],
        invocation_root=invocation_path,
    )
    if event == "PreToolUse" and guarded.decision is Decision.ALLOW and guarded.substantive is True:
        try:
            store.begin_act(
                session_id=session_id,
                approval_bundle_hash=material["bundle_hash"],
                tool_name=tool_name,
                tool_input_hash=digest(tool_input),
                tool_use_id=_tool_use_id(payload),
                project_fingerprint_before=current_fingerprint,
            )
        except Exception as error:
            return _result(Decision.DENY, f"Substantive act boundary rejected: {error}", host=host, event=event)
    return _result(guarded.decision, guarded.reason, host=host, event=event)




















