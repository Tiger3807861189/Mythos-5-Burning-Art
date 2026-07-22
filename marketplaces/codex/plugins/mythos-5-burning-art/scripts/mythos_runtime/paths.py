"""Portable per-user state paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path


APPLICATION_NAME = "Mythos5BurningArt"


def user_state_root(
    *,
    platform: str | None = None,
    environ: dict[str, str] | None = None,
    home: str | os.PathLike[str] | None = None,
) -> Path:
    """Return a neutral user-level state root using platform conventions."""

    env = os.environ if environ is None else environ
    selected = platform or sys.platform
    home_path = Path(home).expanduser() if home is not None else Path.home()
    override = env.get("MYTHOS5_STATE_HOME")
    if override:
        return Path(override).expanduser().resolve(strict=False)
    if selected.startswith("win"):
        base = Path(env.get("LOCALAPPDATA", home_path / "AppData" / "Local"))
        return base / APPLICATION_NAME / "State"
    if selected == "darwin":
        return home_path / "Library" / "Application Support" / APPLICATION_NAME / "State"
    base = Path(env.get("XDG_STATE_HOME", home_path / ".local" / "state"))
    return base / "mythos-5-burning-art"


def prepare_private_directory(path: Path) -> Path:
    if os.name == "nt":
        # POSIX mode bits do not model Windows ACLs. Preserve the inherited
        # per-user ACL instead of applying a mode that can lock out restricted
        # child tokens used by IDE coding agents.
        path.mkdir(parents=True, exist_ok=True)
        return path
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def run_paths(root: Path, repository_id: str, worktree_id: str, run_id: str) -> dict[str, Path]:
    # Keep the storage path below legacy Windows MAX_PATH while retaining 96-bit
    # collision resistance for each independently hashed repository/worktree key.
    repository_key = repository_id[:24]
    worktree_key = worktree_id[:24]
    project = root / "p" / repository_key / "w" / worktree_key
    run = project / "r" / run_id
    return {
        "run": run,
        "agent": run / "agent",
        "authority": run / "authority",
        "events": run / "agent" / "events.jsonl",
        "snapshot": run / "agent" / "state.json",
        "run_lock": run / "agent" / "run.lock",
        "authority_log": run / "authority" / "events.jsonl",
        "approval": run / "authority" / "approval.json",
        "authority_key": root / "authority.key",
    }
