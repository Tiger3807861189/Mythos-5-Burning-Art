"""Translate internal policy decisions into host-supported hook output."""

from __future__ import annotations

from typing import Any

from .policy import Decision


def wire_result(
    decision: Decision,
    reason: str,
    *,
    host: str,
    event: str,
    context: str | None = None,
    system_message: str | None = None,
) -> dict[str, Any]:
    """Return only fields accepted by current Codex and Claude Code hooks.

    A neutral ALLOW does not auto-approve the host's own permission dialog. The
    host remains free to apply its native sandbox and approval policy.
    """

    if host not in {"codex", "claude"}:
        return {"continue": False, "stopReason": reason}

    if event in {"SessionStart", "SubagentStart"}:
        result: dict[str, Any] = {}
        if system_message:
            result["systemMessage"] = system_message
        if context or reason:
            result["hookSpecificOutput"] = {
                "hookEventName": event,
                "additionalContext": context or reason,
            }
        return result

    if event == "PreToolUse":
        if decision is Decision.ALLOW:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    if event == "PermissionRequest":
        if decision is Decision.ALLOW:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {"behavior": "deny", "message": reason},
            }
        }

    if event == "UserPromptSubmit":
        if decision is not Decision.ALLOW:
            return {"decision": "block", "reason": reason}
        result = {}
        if system_message:
            result["systemMessage"] = system_message
        if context or reason:
            result["hookSpecificOutput"] = {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context or reason,
            }
        return result

    if event in {"Stop", "SubagentStop"}:
        if decision is not Decision.ALLOW:
            return {"decision": "block", "reason": reason}
        return {"systemMessage": system_message} if system_message else {}

    return {"systemMessage": system_message or reason}


def failure_result(*, host: str, event: str, reason: str) -> dict[str, Any]:
    """Fail closed where the host can block; warn on non-blocking start events."""

    decision = Decision.NEEDS_HUMAN_JUDGMENT
    return wire_result(
        decision,
        reason,
        host=host,
        event=event,
        context=reason if event in {"SessionStart", "SubagentStart"} else None,
        system_message=reason if event in {"SessionStart", "SubagentStart"} else None,
    )