#!/usr/bin/env python3
"""Install a repository adapter as a recoverable, path-confined transaction."""

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

BEGIN = "<!-- MYTHOS-5-BURNING-ART:BEGIN -->"
END = "<!-- MYTHOS-5-BURNING-ART:END -->"
SCHEMA_VERSION = 3
REPARSE_POINT = 0x0400


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def encode_bytes(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


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
        raise RuntimeError(f"Adapter destination is not repository-relative: {relative}")
    destination = repo.joinpath(*relative.parts)
    cursor = repo
    for part in relative.parts:
        cursor = cursor / part
        if path_exists(cursor) and is_redirect(cursor):
            raise RuntimeError(f"Adapter destination crosses a symlink, junction, or reparse point: {cursor}")
    resolved = destination.resolve(strict=False)
    if resolved != repo and repo not in resolved.parents:
        raise RuntimeError(f"Adapter destination escapes repository: {destination}")
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


def managed_block(text: str) -> str | None:
    start = text.find(BEGIN)
    finish = text.find(END, start + len(BEGIN)) if start >= 0 else -1
    if start < 0 and finish < 0:
        return None
    if start < 0 or finish < 0:
        raise RuntimeError("Repository guidance contains only one Mythos managed marker")
    if text.find(BEGIN, start + len(BEGIN)) >= 0 or text.find(END, finish + len(END)) >= 0:
        raise RuntimeError("Repository guidance contains multiple Mythos managed blocks")
    return text[start : finish + len(END)].strip()


def missing_parent_directories(repo: Path, destination: Path) -> list[str]:
    missing: list[Path] = []
    cursor = destination.parent
    while cursor != repo and not path_exists(cursor):
        missing.append(cursor)
        cursor = cursor.parent
    return [path.relative_to(repo).as_posix() for path in reversed(missing)]


def base_entry(repo: Path, destination: Path, kind: str, prior: bytes | None, result: bytes, owned: bool) -> dict:
    return {
        "path": destination.relative_to(repo).as_posix(),
        "kind": kind,
        "owned": owned,
        "created_file": prior is None,
        "prior_exists": prior is not None,
        "prior_content_b64": encode_bytes(prior) if prior is not None else None,
        "prior_content_sha256": sha256_bytes(prior) if prior is not None else None,
        "content_sha256": sha256_bytes(result),
        "result_content_b64": encode_bytes(result),
        "created_directories": missing_parent_directories(repo, destination) if owned else [],
        "install_state": "planned",
        "uninstall_state": "active",
    }


def plan_guidance(source: Path, repo: Path, relative: Path) -> dict:
    destination = relative_destination(repo, relative)
    block = source.read_text(encoding="utf-8").strip()
    if BEGIN not in block or END not in block:
        raise RuntimeError(f"Adapter guidance lacks managed markers: {source}")
    prior = destination.read_bytes() if path_exists(destination) else None
    existing = prior.decode("utf-8") if prior is not None else ""
    current_block = managed_block(existing)
    if current_block is not None:
        if current_block != block:
            raise RuntimeError(f"A different Mythos managed block already exists in {destination}")
        return base_entry(repo, destination, "managed_block", prior, prior, owned=False)
    merged = existing.rstrip() + ("\n\n" if existing.strip() else "") + block + "\n"
    return base_entry(repo, destination, "managed_block", prior, merged.encode("utf-8"), owned=True)


def plan_file(source: Path, repo: Path, relative: Path) -> dict:
    destination = relative_destination(repo, relative)
    source_bytes = source.read_bytes()
    prior = destination.read_bytes() if path_exists(destination) else None
    if prior is not None and prior != source_bytes:
        raise FileExistsError(f"Refusing to overwrite existing file: {destination}")
    return base_entry(repo, destination, "file", prior, source_bytes, owned=prior is None)


def plan_kit(kit: Path, repo: Path, guidance_name: str) -> list[dict]:
    entries = [plan_guidance(kit / guidance_name, repo, Path(guidance_name))]
    for source in sorted(path for path in kit.rglob("*") if path.is_file() and path.name != guidance_name):
        entries.append(plan_file(source, repo, source.relative_to(kit)))
    return entries


def plan_install(root: Path, repo: Path, host: str) -> list[dict]:
    if host == "claude":
        entries = [plan_guidance(root / "repo-kits" / "codex" / "AGENTS.md", repo, Path("AGENTS.md"))]
        entries.extend(plan_kit(root / "repo-kits" / "claude", repo, "CLAUDE.md"))
        return entries
    return plan_kit(root / "repo-kits" / "codex", repo, "AGENTS.md")


def write_new_manifest(repo: Path, path: Path, payload: dict) -> None:
    if path_exists(path):
        raise FileExistsError(path)
    encoded = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(repo, path, encoded)


def write_manifest(path: Path, payload: dict) -> None:
    encoded = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(path.parent, path, encoded)


def ensure_parent(repo: Path, entry: dict) -> None:
    for relative in entry.get("created_directories", []):
        directory = relative_destination(repo, relative)
        if path_exists(directory):
            if is_redirect(directory) or not directory.is_dir():
                raise RuntimeError(f"Adapter parent is not a safe directory: {directory}")
            continue
        directory.mkdir()
        relative_destination(repo, relative)


def apply_entry(repo: Path, entry: dict) -> None:
    destination = relative_destination(repo, entry["path"])
    if not entry["owned"]:
        current = destination.read_bytes() if path_exists(destination) else None
        if current is None or sha256_bytes(current) != entry["content_sha256"]:
            raise RuntimeError(f"Preexisting adapter content changed during installation: {destination}")
        return
    prior = base64.b64decode(entry["prior_content_b64"]) if entry["prior_exists"] else None
    current = destination.read_bytes() if path_exists(destination) else None
    if current != prior:
        raise RuntimeError(f"Adapter destination changed after preflight: {destination}")
    ensure_parent(repo, entry)
    relative_destination(repo, entry["path"])
    atomic_write_bytes(repo, destination, base64.b64decode(entry["result_content_b64"]))


def restore_entry(repo: Path, entry: dict) -> None:
    if not entry.get("owned"):
        entry["install_state"] = "rolled_back"
        return
    destination = relative_destination(repo, entry["path"])
    prior = base64.b64decode(entry["prior_content_b64"]) if entry["prior_exists"] else None
    current = destination.read_bytes() if path_exists(destination) else None
    result = base64.b64decode(entry["result_content_b64"])
    if current == prior:
        entry["install_state"] = "rolled_back"
        return
    if current != result:
        raise RuntimeError(f"Refusing to roll back modified adapter content: {destination}")
    if prior is None:
        destination.unlink()
    else:
        atomic_write_bytes(repo, destination, prior)
    entry["install_state"] = "rolled_back"


def remove_created_directories(repo: Path, entries: list[dict]) -> None:
    directories = {
        relative
        for entry in entries
        for relative in entry.get("created_directories", [])
    }
    for relative in sorted(directories, key=lambda item: len(Path(item).parts), reverse=True):
        directory = relative_destination(repo, relative)
        if path_exists(directory) and directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


def rollback_install(repo: Path, manifest: Path, payload: dict) -> list[str]:
    errors: list[str] = []
    for entry in reversed(payload["changes"]):
        try:
            restore_entry(repo, entry)
            write_manifest(manifest, payload)
        except Exception as exc:  # Preserve all remaining recovery evidence.
            errors.append(f"{entry['path']}: {exc}")
    try:
        remove_created_directories(repo, payload["changes"])
    except Exception as exc:
        errors.append(f"created directories: {exc}")
    if errors:
        payload["status"] = "install_failed"
        payload["rollback_errors"] = errors
        write_manifest(manifest, payload)
    else:
        manifest.unlink()
    return errors


def _install_locked(root: Path, repo: Path, host: str, dry_run: bool, fail_after: int | None = None) -> list[dict]:
    root = root.expanduser().resolve()
    repo = normalize_repo(repo)
    if not (root / "repo-kits" / host).is_dir():
        raise FileNotFoundError(root / "repo-kits" / host)
    manifest = manifest_path(repo, host)
    if path_exists(manifest):
        raise FileExistsError(f"Install manifest already exists: {manifest}")

    entries = plan_install(root, repo, host)
    if dry_run:
        return entries

    payload = {
        "schema_version": SCHEMA_VERSION,
        "host": host,
        "status": "installing",
        "changes": entries,
    }
    write_new_manifest(repo, manifest, payload)
    mutations = 0
    try:
        for entry in entries:
            apply_entry(repo, entry)
            entry["install_state"] = "applied"
            write_manifest(manifest, payload)
            if entry["owned"]:
                mutations += 1
                if fail_after is not None and mutations >= fail_after:
                    raise RuntimeError("Simulated mid-install failure")
        payload["status"] = "installed"
        write_manifest(manifest, payload)
        return entries
    except Exception as exc:
        errors = rollback_install(repo, manifest, payload)
        if errors:
            raise RuntimeError(f"Installation failed ({exc}); automatic rollback was incomplete: {'; '.join(errors)}") from exc
        raise


def install(root: Path, repo: Path, host: str, dry_run: bool, fail_after: int | None = None) -> list[dict]:
    repo = normalize_repo(repo)
    if dry_run:
        return _install_locked(root, repo, host, True, fail_after)
    with adapter_lock(repo):
        return _install_locked(root, repo, host, False, fail_after)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--host", choices=["codex", "claude"], required=True)
    parser.add_argument("--apply", action="store_true", help="Apply changes. The default is a dry run.")
    args = parser.parse_args()
    injected = os.environ.get("MYTHOS_ADAPTER_TEST_FAIL_INSTALL_AFTER")
    fail_after = int(injected) if injected else None
    changes = install(args.root, args.repo, args.host, dry_run=not args.apply, fail_after=fail_after)
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "host": args.host, "changes": changes}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Adapter installation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)