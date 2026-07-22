"""Canonical data, path, and project identity helpers.

The canonical JSON format is UTF-8, NFC-normalized, LF-only, compact, and
sorted by key.  Hashes in the runtime always operate on this representation.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable


SCHEMA_VERSION = "1"
_WINDOWS_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    if isinstance(value, dict):
        return {_normalize(str(key)): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TypeError(f"Unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    """Return the one canonical UTF-8 representation used by all hashes."""

    normalized = _normalize(value)
    text = json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return text.encode("utf-8")


def canonical_text(value: Any) -> str:
    return canonical_json(value).decode("utf-8") + "\n"


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalize_path_text(path: str | os.PathLike[str], *, platform: str | None = None) -> str:
    """Normalize a path for identity without requiring it to exist.

    Windows paths are case-folded because drive and UNC paths are normally
    case-insensitive. POSIX paths retain case. Separators are always `/`.
    """

    raw = unicodedata.normalize("NFC", os.fspath(path)).replace("\r", "").strip()
    windows = platform == "windows" or (platform is None and bool(_WINDOWS_ABSOLUTE.match(raw)))
    if windows:
        candidate = str(PureWindowsPath(raw)).replace("\\", "/")
        return candidate.casefold()
    return str(PurePosixPath(raw.replace("\\", "/")))


def canonical_existing_path(path: str | os.PathLike[str]) -> str:
    resolved = Path(path).expanduser().resolve(strict=False)
    text = unicodedata.normalize("NFC", str(resolved)).replace("\\", "/")
    if os.name == "nt":
        text = text.casefold()
    return text


def _git(root: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_bytes(root: Path, *arguments: str) -> bytes | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            timeout=20,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def project_identity(path: str | os.PathLike[str]) -> dict[str, str | bool]:
    """Return stable repository and worktree identities for an existing project."""

    start = Path(path).expanduser().resolve(strict=False)
    top = _git(start, "rev-parse", "--show-toplevel")
    if top:
        worktree = Path(top).resolve(strict=False)
        common = _git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if not common:
            common = _git(worktree, "rev-parse", "--git-common-dir")
        common_path = Path(common) if common else worktree / ".git"
        if not common_path.is_absolute():
            common_path = worktree / common_path
        repository_key = canonical_existing_path(common_path)
        worktree_key = canonical_existing_path(worktree)
        return {
            "is_git": True,
            "project_root": worktree_key,
            "repository_id": digest({"kind": "git-common-dir", "path": repository_key}),
            "worktree_id": digest({"kind": "git-worktree", "path": worktree_key}),
        }
    root_key = canonical_existing_path(start)
    identifier = digest({"kind": "directory", "path": root_key})
    return {
        "is_git": False,
        "project_root": root_key,
        "repository_id": identifier,
        "worktree_id": identifier,
    }


def _iter_project_files(root: Path) -> Iterable[Path]:
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names if name != ".git")
        for name in sorted(files):
            yield Path(directory) / name


_DEFAULT_EXCLUDED_DIRS = {
    ".cache", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    ".venv", "__pycache__", "build", "coverage", "dist", "node_modules",
    "target", "venv",
}


def _scope_includes_directory(relative: str, include_paths: Iterable[str]) -> bool:
    prefix = normalize_path_text(relative, platform="posix").rstrip("/")
    return any(
        normalize_path_text(item, platform="posix").rstrip("/") == prefix
        or normalize_path_text(item, platform="posix").startswith(prefix + "/")
        for item in include_paths
    )


def project_content_snapshot(
    path: str | os.PathLike[str],
    *,
    include_paths: Iterable[str] = (),
    include_generated: bool = False,
) -> list[dict[str, str]]:
    """Capture exact regular-file bytes and link-target bytes for hook-owned verification.

    Common generated dependency/cache roots are skipped unless an approved path
    explicitly targets them or ``include_generated`` is true. Command-bearing
    scopes set that flag because an exact shell command can mutate any local
    generated root. Ordinary repositories remain bounded when no command exists.
    """

    root = Path(path).expanduser().resolve(strict=False)
    top = _git(root, "rev-parse", "--show-toplevel")
    if top:
        root = Path(top).resolve(strict=False)
    if not root.exists():
        return []
    includes = tuple(str(item) for item in include_paths)
    entries: list[dict[str, str]] = []
    for directory, names, files in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        retained: list[str] = []
        for name in sorted(names):
            if name == ".git":
                continue
            candidate = directory_path / name
            relative = normalize_path_text(candidate.relative_to(root).as_posix(), platform="posix")
            if name.casefold() in _DEFAULT_EXCLUDED_DIRS and not include_generated and not _scope_includes_directory(relative, includes):
                continue
            if candidate.is_symlink():
                target = os.readlink(candidate)
                raw = target.encode("utf-8", errors="replace")
                entries.append({
                    "path": relative,
                    "kind": "symlink",
                    "sha256": digest_bytes(raw),
                    "encoding": "base64",
                    "data": base64.b64encode(raw).decode("ascii"),
                })
            else:
                retained.append(name)
        names[:] = retained
        for name in sorted(files):
            candidate = directory_path / name
            relative = normalize_path_text(candidate.relative_to(root).as_posix(), platform="posix")
            if candidate.is_symlink():
                target = os.readlink(candidate)
                raw = target.encode("utf-8", errors="replace")
                entries.append({
                    "path": relative,
                    "kind": "symlink",
                    "sha256": digest_bytes(raw),
                    "encoding": "base64",
                    "data": base64.b64encode(raw).decode("ascii"),
                })
                continue
            try:
                raw = candidate.read_bytes()
                entries.append({
                    "path": relative,
                    "kind": "file",
                    "sha256": digest_bytes(raw),
                    "encoding": "base64",
                    "data": base64.b64encode(raw).decode("ascii"),
                })
            except (OSError, PermissionError) as error:
                entries.append({
                    "path": relative,
                    "kind": "unreadable",
                    "sha256": digest({"unreadable": type(error).__name__}),
                })
    return sorted(entries, key=lambda item: (item["path"], item["kind"], item["sha256"]))


def project_content_manifest(
    path: str | os.PathLike[str],
    *,
    include_paths: Iterable[str] = (),
    include_generated: bool = False,
) -> list[dict[str, str]]:
    """Return the content-only view of a hook-owned project snapshot."""

    return [
        {"path": item["path"], "kind": item["kind"], "sha256": item["sha256"]}
        for item in project_content_snapshot(
            path, include_paths=include_paths, include_generated=include_generated,
        )
    ]
def compute_base_fingerprint(path: str | os.PathLike[str]) -> str:
    """Fingerprint tracked and relevant untracked project content.

    Git-ignored generated trees are excluded from the global stale-plan guard.
    Approved paths in such trees are separately captured by the scoped content
    snapshot used by the mutation and verification gates.
    """

    root = Path(path).expanduser().resolve(strict=False)
    top = _git(root, "rev-parse", "--show-toplevel")
    if top:
        git_root = Path(top)
        head = _git(git_root, "rev-parse", "HEAD") or "UNBORN"
        tracked_diff = _git_bytes(
            git_root, "-c", "core.fsmonitor=false", "diff", "--binary",
            "--no-ext-diff", "--no-textconv", "HEAD", "--",
        )
        if tracked_diff is None:
            tracked_diff = _git_bytes(
                git_root, "-c", "core.fsmonitor=false", "diff", "--binary",
                "--no-ext-diff", "--no-textconv", "--cached", "--",
            ) or b""
        status = _git_bytes(
            git_root, "-c", "core.fsmonitor=false", "status",
            "--porcelain=v2", "-z", "--untracked-files=all",
        ) or b""
        tracked_output = _git_bytes(git_root, "ls-files", "-z") or b""
        untracked_output = _git_bytes(
            git_root, "ls-files", "--others", "--exclude-standard", "-z",
        ) or b""

        def content_entries(raw_paths: bytes) -> list[dict[str, str]]:
            entries: list[dict[str, str]] = []
            for raw_path in sorted(item for item in raw_paths.split(b"\0") if item):
                relative = raw_path.decode("utf-8", errors="replace")
                parts = PurePosixPath(relative).parts
                if any(part == ".git" for part in parts):
                    continue
                if any(part.casefold() in _DEFAULT_EXCLUDED_DIRS for part in parts):
                    continue
                file_path = git_root / relative
                if file_path.is_symlink():
                    value = digest_bytes(os.readlink(file_path).encode("utf-8", errors="replace"))
                    kind = "symlink"
                else:
                    try:
                        value = digest_bytes(file_path.read_bytes())
                        kind = "file"
                    except (OSError, PermissionError) as error:
                        value = digest({"unreadable": type(error).__name__})
                        kind = "unreadable"
                entries.append({
                    "path": normalize_path_text(relative, platform="posix"),
                    "kind": kind,
                    "sha256": value,
                })
            return entries

        return digest({
            "kind": "git",
            "head": head,
            "tracked_diff_sha256": digest_bytes(tracked_diff),
            "tracked": content_entries(tracked_output),
            "status_sha256": digest_bytes(status),
            "untracked": content_entries(untracked_output),
        })

    if not root.exists():
        return digest({"kind": "missing", "root": canonical_existing_path(root)})
    return digest({"kind": "directory", "entries": project_content_manifest(root)})
def plan_material(
    *,
    plan: Any,
    scope: Any,
    acceptance: Any,
    critic: Any,
    base_fingerprint: str,
) -> dict[str, str]:
    """Build hashes whose changes invalidate an approval."""

    material = {
        "base_fingerprint": base_fingerprint,
        "plan_hash": digest(plan),
        "scope_hash": digest(scope),
        "acceptance_hash": digest(acceptance),
        "critic_hash": digest(critic),
    }
    material["bundle_hash"] = digest({"schema": SCHEMA_VERSION, **material})
    return material





