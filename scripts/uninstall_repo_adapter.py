#!/usr/bin/env python3
"""Resume or complete a repository-adapter uninstall without escaping the repository."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "src" / "shared" / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from mythos_runtime.locking import FileLock

REPARSE_POINT = 0x0400
SCHEMA_VERSION = 3
RECOVERY_FIELDS = (
    "created_file",
    "prior_exists",
    "prior_content_b64",
    "prior_content_sha256",
    "content_sha256",
    "result_content_b64",
    "created_directories",
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def path_exists(path: Path) -> bool:
    return os.path.lexists(path)


def is_redirect(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, FileNotFoundError, OSError):
        return False
    return bool(attributes & REPARSE_POINT)


def normalize_repo(path: Path) -> Path:
    candidate = Path(os.path.abspath(os.fspath(path.expanduser())))
    if not candidate.is_dir():
        raise NotADirectoryError(candidate)
    if is_redirect(candidate):
        raise RuntimeError(f"Repository root must not be a symlink, junction, or reparse point: {candidate}")
    return candidate.resolve()


def relative_destination(repo: Path, relative: Path | str) -> Path:
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"Manifest destination is not repository-relative: {relative}")
    destination = repo.joinpath(*relative.parts)
    cursor = repo
    for part in relative.parts:
        cursor = cursor / part
        if path_exists(cursor) and is_redirect(cursor):
            raise RuntimeError(f"Manifest destination crosses a symlink, junction, or reparse point: {cursor}")
    resolved = destination.resolve(strict=False)
    if resolved != repo and repo not in resolved.parents:
        raise RuntimeError(f"Manifest destination escapes repository: {destination}")
    return destination


def adapter_lock(repo: Path) -> FileLock:
    configured = os.environ.get("MYTHOS5_STATE_HOME")
    state_root = Path(configured).expanduser().resolve(strict=False) if configured else Path(tempfile.gettempdir()) / "mythos-5-burning-art"
    try:
        if os.path.normcase(os.path.commonpath([str(state_root), str(repo)])) == os.path.normcase(str(repo)):
            raise RuntimeError("MYTHOS5_STATE_HOME must be outside the repository")
    except ValueError:
        pass
    key = hashlib.sha256(os.path.normcase(str(repo)).encode("utf-8")).hexdigest()
    return FileLock(state_root / "adapter-locks" / f"{key}.lock", timeout=30.0)


def atomic_write_bytes(repo: Path, destination: Path, payload: bytes) -> None:
    relative_destination(repo, destination.relative_to(repo))
    destination.parent.mkdir(parents=True, exist_ok=True)
    relative_destination(repo, destination.relative_to(repo))
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        relative_destination(repo, destination.relative_to(repo))
        os.replace(temporary, destination)
    finally:
        if path_exists(temporary):
            temporary.unlink()

def manifest_path(repo: Path, host: str) -> Path:
    return relative_destination(repo, f".mythos-adapter-install-{host}.json")


def write_manifest(repo: Path, path: Path, payload: dict) -> None:
    encoded = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(repo, path, encoded)


def load_manifest(repo: Path, host: str) -> tuple[Path, dict]:
    path = manifest_path(repo, host)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(f"Unsupported adapter manifest schema in {path}")
    if payload.get("host") != host or not isinstance(payload.get("changes"), list):
        raise RuntimeError(f"Invalid adapter manifest: {path}")
    for entry in payload["changes"]:
        relative_destination(repo, entry.get("path", ""))
    return path, payload


def load_other_manifest(repo: Path, host: str) -> tuple[Path, dict] | None:
    other = "claude" if host == "codex" else "codex"
    path = manifest_path(repo, other)
    if not path_exists(path):
        return None
    return load_manifest(repo, other)


def decoded(entry: dict, name: str) -> bytes | None:
    value = entry.get(name)
    return base64.b64decode(value) if value is not None else None


def entry_content_state(repo: Path, entry: dict) -> str:
    destination = relative_destination(repo, entry["path"])
    current = destination.read_bytes() if path_exists(destination) else None
    prior = decoded(entry, "prior_content_b64") if entry.get("prior_exists") else None
    result = decoded(entry, "result_content_b64")
    if current == result:
        return "installed"
    if current == prior:
        return "restored"
    raise RuntimeError(f"Refusing to alter modified adapter content: {destination}")


def active_reference(repo: Path, payload: dict | None, relative: str) -> int | None:
    if payload is None:
        return None
    for index, entry in enumerate(payload.get("changes", [])):
        if entry.get("path") != relative or entry.get("uninstall_state", "active") == "done":
            continue
        state = entry_content_state(repo, entry)
        if state == "installed":
            return index
    return None


def public_action(action: dict) -> dict:
    return {key: value for key, value in action.items() if key not in {"other_index", "state"}}


def plan_actions(repo: Path, payload: dict, other_payload: dict | None) -> list[dict]:
    actions: list[dict] = []
    for index in range(len(payload["changes"]) - 1, -1, -1):
        entry = payload["changes"][index]
        destination = relative_destination(repo, entry["path"])
        if entry.get("uninstall_state", "active") == "done":
            actions.append(
                {
                    "index": index,
                    "path": str(destination),
                    "kind": entry["kind"],
                    "action": "already_done",
                    "transfer_ownership": False,
                    "other_index": None,
                    "state": "restored",
                }
            )
            continue

        state = entry_content_state(repo, entry)
        owned = bool(entry.get("owned"))
        other_index = active_reference(repo, other_payload, entry["path"])
        if not owned:
            action = "keep_preexisting"
        elif state == "restored":
            action = "already_removed"
        elif other_index is not None:
            action = "keep_shared"
        else:
            action = "remove"
        actions.append(
            {
                "index": index,
                "path": str(destination),
                "kind": entry["kind"],
                "action": action,
                "transfer_ownership": bool(action == "keep_shared" and owned),
                "other_index": other_index,
                "state": state,
            }
        )
    return actions


def transfer_ownership(source: dict, target: dict) -> None:
    target["owned"] = True
    target["install_state"] = "applied"
    for field in RECOVERY_FIELDS:
        target[field] = source.get(field)


def restore_owned_entry(repo: Path, entry: dict) -> None:
    destination = relative_destination(repo, entry["path"])
    state = entry_content_state(repo, entry)
    if state == "restored":
        return
    prior = decoded(entry, "prior_content_b64") if entry.get("prior_exists") else None
    if prior is None:
        destination.unlink()
    else:
        atomic_write_bytes(repo, destination, prior)


def remove_created_directories(repo: Path, entries: list[dict]) -> None:
    directories = {
        relative
        for entry in entries
        if entry.get("owned")
        for relative in entry.get("created_directories", [])
    }
    for relative in sorted(directories, key=lambda item: len(Path(item).parts), reverse=True):
        directory = relative_destination(repo, relative)
        if path_exists(directory) and directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


def _uninstall_locked(repo: Path, host: str, dry_run: bool, fail_after: int | None = None) -> list[dict]:
    repo = normalize_repo(repo)
    manifest, payload = load_manifest(repo, host)
    other_record = load_other_manifest(repo, host)
    other_path = other_record[0] if other_record else None
    other_payload = other_record[1] if other_record else None
    actions = plan_actions(repo, payload, other_payload)
    if dry_run:
        return [public_action(action) for action in actions]

    mutations = 0
    payload["status"] = "uninstalling"
    write_manifest(repo, manifest, payload)
    for action in actions:
        entry = payload["changes"][action["index"]]
        if entry.get("uninstall_state", "active") == "done":
            continue

        if action["transfer_ownership"]:
            if other_payload is None or other_path is None or action["other_index"] is None:
                raise RuntimeError(f"Shared ownership target disappeared for {entry['path']}")
            target = other_payload["changes"][action["other_index"]]
            transfer_ownership(entry, target)
            write_manifest(repo, other_path, other_payload)
            mutations += 1
            if fail_after is not None and mutations >= fail_after:
                raise RuntimeError("Simulated mid-uninstall failure")
        elif action["action"] == "remove":
            restore_owned_entry(repo, entry)
            mutations += 1
            if fail_after is not None and mutations >= fail_after:
                raise RuntimeError("Simulated mid-uninstall failure")

        entry["uninstall_state"] = "done"
        write_manifest(repo, manifest, payload)

    remove_created_directories(repo, payload["changes"])
    manifest.unlink()
    return [public_action(action) for action in actions]


def uninstall(repo: Path, host: str, dry_run: bool, fail_after: int | None = None) -> list[dict]:
    repo = normalize_repo(repo)
    if dry_run:
        return _uninstall_locked(repo, host, True, fail_after)
    with adapter_lock(repo):
        return _uninstall_locked(repo, host, False, fail_after)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--host", choices=["codex", "claude"], required=True)
    parser.add_argument("--apply", action="store_true", help="Apply removal. The default is a dry run.")
    args = parser.parse_args()
    injected = os.environ.get("MYTHOS_ADAPTER_TEST_FAIL_UNINSTALL_AFTER")
    fail_after = int(injected) if injected else None
    actions = uninstall(args.repo, args.host, dry_run=not args.apply, fail_after=fail_after)
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "host": args.host, "actions": actions}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Adapter removal failed: {exc}", file=sys.stderr)
        raise SystemExit(1)