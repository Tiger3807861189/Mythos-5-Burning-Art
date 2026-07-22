"""Conservative task and tool mutation classification."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    NEEDS_HUMAN_JUDGMENT = "NEEDS_HUMAN_JUDGMENT"


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    reason: str
    substantive: bool | None = None


MUTATION_WORDS = re.compile(
    r"\b(build|create|change|edit|implement|fix|repair|delete|remove|move|rename|install|deploy|migrate|commit|push|write)\b",
    re.IGNORECASE,
)
READ_ONLY_WORDS = re.compile(r"\b(explain|summarize|review|inspect|read|report status|answer)\b", re.IGNORECASE)


def classify_task(request: str) -> PolicyResult:
    if MUTATION_WORDS.search(request):
        return PolicyResult(Decision.DENY, "The request asks for implementation or another side effect", True)
    if READ_ONLY_WORDS.search(request):
        return PolicyResult(Decision.ALLOW, "The request is explicitly read-only", False)
    return PolicyResult(Decision.NEEDS_HUMAN_JUDGMENT, "Task intent is not safely classifiable", None)


READ_TOOLS = {"read", "grep", "glob", "ls", "find", "websearch", "webfetch", "view_image"}
WRITE_TOOLS = {"write", "edit", "multiedit", "notebookedit", "apply_patch"}
SHELL_TOOLS = {"bash", "shell", "shell_command", "exec_command", "powershell", "terminal"}
CONTROL_TOOLS = {
    "agent", "askuserquestion", "exitplanmode", "skill", "todowrite",
    "updateplan", "requestuserinput", "spawnagent", "waitagent",
    "listagents", "sendmessage", "followuptask", "interruptagent",
    "taskcreate", "taskupdate", "taskget", "tasklist",
}
SHELL_META = re.compile(r"[;&|><`\n\r]|\$\(|\b(?:rm|del|erase|move|mv|cp|copy|install|commit|push|reset|checkout)\b", re.IGNORECASE)
SAFE_SHELL = re.compile(
    r"^(?:pwd|"
    r"git\s+--no-pager\s+--no-optional-locks\s+-c\s+core\.fsmonitor=false\s+(?:"
    r"status(?:\s+(?:--short|--branch|--porcelain(?:=v[12])?|--untracked-files=(?:no|normal|all)))*|"
    r"diff\s+--no-ext-diff\s+--no-textconv(?:\s+(?:--cached|--stat|--name-only|--name-status))*"
    r"(?:\s+--(?:\s+[^;&|><`]*)?)?|"
    r"rev-parse\s+(?:--show-toplevel|--git-common-dir|--is-inside-work-tree|HEAD)"
    r")"
    r")$",
    re.IGNORECASE,
)
SIDE_EFFECT_READ_OPTIONS = re.compile(
    r"(?:^|\s)(?:--output(?:=|\s)|--ext-diff\b|--textconv\b|--pre(?:-glob)?(?:=|\s)|--generate(?:=|\s))",
    re.IGNORECASE,
)
SAFE_DISCOVERY_SHELL = re.compile(
    r"^(?:(?:rg(?:\.exe)?|Get-Content|Get-ChildItem|Get-Item|Select-String|"
    r"cat|head|ls|stat|tail|wc|file|findstr)(?:\s+[^;&|><`$@{}\r\n]+)?)$",
    re.IGNORECASE,
)


def _normalized_tool(tool_name: str) -> str:
    # Do not let connector namespaces inherit authority from a native tool name
    # suffix (for example, mcp__slack__send_message is not agent coordination).
    token = tool_name if "__" in tool_name else tool_name.rsplit("__", 1)[-1]
    return token.replace("-", "_").casefold().replace("_", "")


def classify_tool(tool_name: str, tool_input: dict[str, Any] | None = None) -> PolicyResult:
    compact = _normalized_tool(tool_name)
    if compact in {name.replace("_", "") for name in READ_TOOLS}:
        return PolicyResult(Decision.ALLOW, "Tool is observable and read-only", False)
    if compact in {name.replace("_", "") for name in CONTROL_TOOLS}:
        return PolicyResult(Decision.ALLOW, "Host-native planning, questioning, skill, or agent coordination action", False)
    if compact in {name.replace("_", "") for name in WRITE_TOOLS}:
        return PolicyResult(Decision.DENY, "Tool performs a filesystem mutation", True)
    if compact in {name.replace("_", "") for name in SHELL_TOOLS}:
        data = tool_input or {}
        command = str(data.get("command", data.get("cmd", ""))).strip()
        if command and (SAFE_SHELL.fullmatch(command) or SAFE_DISCOVERY_SHELL.fullmatch(command)) and not SHELL_META.search(command) and not SIDE_EFFECT_READ_OPTIONS.search(command):
            return PolicyResult(Decision.ALLOW, "Command matches the narrow read-only allowlist", False)
        if command and (SHELL_META.search(command) or SIDE_EFFECT_READ_OPTIONS.search(command)):
            return PolicyResult(Decision.DENY, "Shell command contains a mutation, executable filter, or output-file option", True)
        return PolicyResult(Decision.NEEDS_HUMAN_JUDGMENT, "Shell effects cannot be observed reliably", None)
    return PolicyResult(
        Decision.NEEDS_HUMAN_JUDGMENT,
        "Unsupported or unobservable tool; no enforcement coverage is claimed",
        None,
    )


def _candidate_paths(tool_name: str, tool_input: dict[str, Any]) -> tuple[list[str], str | None]:
    compact = _normalized_tool(tool_name)
    paths: list[str] = []
    for key in ("file_path", "path", "destination", "target"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            paths.append(value.strip())
    if compact != "applypatch":
        return paths, None
    patch = tool_input.get("patch", tool_input.get("input", ""))
    if not isinstance(patch, str) or not patch.strip():
        return [], "apply_patch input is missing"
    patch_paths: list[str] = []
    for line in patch.splitlines():
        if not line.startswith("*** "):
            continue
        if line in {"*** Begin Patch", "*** End Patch"}:
            continue
        match = re.fullmatch(r"\*\*\* (?:Add|Update|Delete) File: (.+)", line)
        if match is None:
            match = re.fullmatch(r"\*\*\* Move to: (.+)", line)
        if match is None:
            return [], f"unrecognized apply_patch directive: {line}"
        candidate = match.group(1).strip()
        if not candidate or candidate in {"/dev/null", "NUL"}:
            return [], f"invalid apply_patch path directive: {line}"
        patch_paths.append(candidate)
    if not patch_paths:
        return [], "apply_patch contains no recognized path directives"
    return paths + patch_paths, None


_WINDOWS_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE)
_EXTERNAL_COMMAND = re.compile(r"\b(?:deploy|publish|push|ssh|scp|curl|wget|invoke-restmethod|invoke-webrequest|terraform\s+apply|kubectl\s+apply|database|migration)\b", re.IGNORECASE)
_SHELL_PATH_ESCAPE = re.compile(r"(?:^|[\s'\"=/\\])(?:[A-Za-z]:[\\/]|\\\\|/|\.\.(?:[\\/]|$))")
_UNOBSERVABLE_LOCAL_COMMAND = re.compile(r"\b(?:git\s+(?:add|commit|branch|tag|stash|switch|checkout|reset)|chmod|chown|attrib|mklink|junction|ln\s|mkdir|rmdir|touch|new-item\s+[^\r\n]*(?:directory|junction|symboliclink|hardlink))\b", re.IGNORECASE)


def _safe_portable_path_text(value: str) -> bool:
    raw = value.strip()
    if not raw or raw.startswith(("\\\\?\\", "\\\\.\\", "\\??\\", "//?/", "//./", "\\\\")):
        return False
    normalized = raw.replace("\\", "/")
    drive = bool(re.match(r"^[A-Za-z]:/", normalized))
    remainder = normalized[3:] if drive else normalized
    if ":" in remainder:
        return False
    for component in (item for item in remainder.split("/") if item not in {"", ".", ".."}):
        if component.endswith((".", " ")) or _WINDOWS_RESERVED.fullmatch(component):
            return False
    return True

def _is_reparse(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    return stat.S_ISLNK(info.st_mode) or bool(reparse_flag and attributes & reparse_flag)


def _has_reparse_component(path: Path, boundary: Path) -> bool:
    current = path
    while True:
        if _is_reparse(current):
            return True
        if current == boundary:
            return False
        parent = current.parent
        if parent == current:
            return True
        current = parent


def _lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _inside(candidate: Path, root: Path) -> bool:
    try:
        return os.path.normcase(os.path.commonpath([str(candidate), str(root)])) == os.path.normcase(str(root))
    except ValueError:
        return False


def _within(candidate: Path, roots: list[tuple[Path, bool]], project_root: Path) -> bool:
    try:
        project = _lexical(project_root)
        lexical_candidate = _lexical(candidate)
        if not _inside(lexical_candidate, project) or _has_reparse_component(lexical_candidate, project):
            return False
        if lexical_candidate.exists() and lexical_candidate.is_file() and lexical_candidate.stat().st_nlink > 1:
            return False
        for root, recursive in roots:
            lexical_root = _lexical(root)
            if not _inside(lexical_root, project) or _has_reparse_component(lexical_root, project):
                continue
            if lexical_candidate == lexical_root or (recursive and _inside(lexical_candidate, lexical_root)):
                return True
        return False
    except (OSError, ValueError):
        return False


def approved_scope_is_safe(*, project_root: str | os.PathLike[str], scope: Any) -> bool:
    """Reject scope roots that are absolute, traverse upward, or cross reparse points."""
    root = _lexical(Path(project_root))
    scope_paths = scope.get("paths", []) if isinstance(scope, dict) else []
    if not isinstance(scope_paths, list):
        return False
    for item in scope_paths:
        if not isinstance(item, str) or not _safe_portable_path_text(item):
            return False
        normalized = item.replace("\\", "/")
        path = Path(item)
        if path.is_absolute() or re.match(r"^[A-Za-z]:/", normalized):
            return False
        components = [component for component in normalized.split("/") if component not in {"", "."}]
        if ".." in components:
            return False
        lexical = _lexical(root / item)
        if not _inside(lexical, root) or _has_reparse_component(lexical, root):
            return False
    return True


def approved_scope_contains_paths(
    *,
    project_root: str | os.PathLike[str],
    scope: Any,
    candidates: list[str],
) -> bool:
    root = _lexical(Path(project_root))
    scope_paths = scope.get("paths", []) if isinstance(scope, dict) else []
    if not approved_scope_is_safe(project_root=root, scope=scope) or not all(
        isinstance(item, str) and _safe_portable_path_text(item) for item in candidates
    ):
        return False
    roots = [(root / item, item.endswith(("/", "\\"))) for item in scope_paths]
    return bool(roots) and all(
        _within((root / item) if not Path(item).is_absolute() else Path(item), roots, root)
        for item in candidates
    )

def approved_tool_guard(
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    project_root: str | os.PathLike[str],
    scope: Any,
    invocation_root: str | os.PathLike[str] | None = None,
) -> PolicyResult:
    classification = classify_tool(tool_name, tool_input)
    normalized = _normalized_tool(tool_name)
    if normalized in {name.replace("_", "") for name in SHELL_TOOLS}:
        command = str(tool_input.get("command", tool_input.get("cmd", ""))).strip()
        allowed_commands = scope.get("commands", []) if isinstance(scope, dict) else []
        environment = tool_input.get("env", tool_input.get("environment"))
        if environment not in (None, {}, []):
            return PolicyResult(Decision.DENY, "Shell commands do not permit environment overrides", True)
        root = Path(project_root)
        effective_workdir = tool_input.get("workdir", tool_input.get("cwd", invocation_root or root))
        if not isinstance(effective_workdir, (str, os.PathLike)) or _lexical(Path(effective_workdir)) != _lexical(root):
            return PolicyResult(Decision.DENY, "Shell commands must run from the exact governed project root", True)
        if _has_reparse_component(_lexical(Path(effective_workdir)), _lexical(root)):
            return PolicyResult(Decision.DENY, "Shell working directory crosses a reparse point", True)
        if _SHELL_PATH_ESCAPE.search(command):
            return PolicyResult(Decision.DENY, "Shell commands must not address paths outside the governed project root", True)
        if _EXTERNAL_COMMAND.search(command):
            return PolicyResult(Decision.DENY, "Portable Mythos packages do not authorize unobservable external shell effects", True)
        if _UNOBSERVABLE_LOCAL_COMMAND.search(command):
            return PolicyResult(Decision.DENY, "Portable Mythos packages do not authorize Git, permission, link, or directory-only mutations", True)
        if classification.decision is Decision.ALLOW:
            return classification
        if command and command.casefold() not in {"none", "n/a", "not applicable"} and command in allowed_commands:
            return PolicyResult(Decision.ALLOW, "Exact approved shell command at the governed project root", True)
        return PolicyResult(Decision.DENY, "Shell command is not an exact approved command", True)
    if classification.decision is Decision.ALLOW:
        return classification
    if classification.decision is Decision.NEEDS_HUMAN_JUDGMENT:
        return classification
    candidates, path_error = _candidate_paths(tool_name, tool_input)
    if path_error:
        return PolicyResult(Decision.DENY, path_error, True)
    if not candidates:
        return PolicyResult(Decision.NEEDS_HUMAN_JUDGMENT, "Mutation target is not observable", None)
    if approved_scope_contains_paths(project_root=project_root, scope=scope, candidates=candidates):
        return PolicyResult(Decision.ALLOW, "All mutation targets are inside the approved scope", True)
    return PolicyResult(Decision.DENY, "Mutation target falls outside the approved scope", True)