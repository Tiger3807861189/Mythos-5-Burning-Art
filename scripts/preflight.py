#!/usr/bin/env python3
"""Portable readiness check for Mythos 5 Burning Art."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


def state_root() -> Path:
    override = os.environ.get("MYTHOS5_STATE_HOME")
    if override:
        return Path(override).expanduser().resolve(strict=False)
    home = Path.home()
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "Mythos5BurningArt" / "State"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Mythos5BurningArt" / "State"
    return Path(os.environ.get("XDG_STATE_HOME", home / ".local" / "state")) / "mythos-5-burning-art"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--host", choices=["codex", "claude", "both"], default="both")
    parser.add_argument("--skip-write-probe", action="store_true")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    checks: list[dict[str, object]] = []

    version_ok = sys.version_info >= (3, 11)
    checks.append({"check": "python_version", "ok": version_ok, "value": sys.version.split()[0], "required": ">=3.11"})
    required = [root / "spec", root / "repo-kits", root / "scripts", root / "src" / "shared" / "skills"]
    missing = [str(path) for path in required if not path.exists()]
    checks.append({"check": "suite_layout", "ok": not missing, "missing": missing})

    hosts = ["codex", "claude"] if args.host == "both" else [args.host]
    for host in hosts:
        executable = shutil.which(host)
        checks.append({"check": f"{host}_executable", "ok": executable is not None, "value": executable})
        source = root / "src" / host / "mythos-5-burning-art"
        checks.append({"check": f"{host}_adapter", "ok": source.is_dir(), "value": str(source)})

    target = state_root()
    write_ok = True
    error: str | None = None
    if not args.skip_write_probe:
        try:
            target.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(prefix="preflight-", suffix=".tmp", dir=target)
            os.close(descriptor)
            Path(name).unlink()
        except OSError as exc:
            write_ok = False
            error = f"{type(exc).__name__}: {exc}"
    checks.append({
        "check": "state_root",
        "ok": None if args.skip_write_probe else write_ok,
        "skipped": args.skip_write_probe,
        "value": str(target),
        "error": error,
    })

    ok = all(bool(item["ok"]) for item in checks if not item.get("skipped"))
    print(json.dumps({"ok": ok, "checks": checks}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())