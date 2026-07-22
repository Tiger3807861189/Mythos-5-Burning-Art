#!/usr/bin/env python3
"""Run current host-provided validators and preserve hash-bound release evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SUITE = "mythos-5-burning-art"
SKILLS = (
    "mythos-build",
    "mythos-debug",
    "mythos-discover",
    "mythos-explain",
    "mythos-options",
    "mythos-orchestrate",
    "mythos-plan",
    "mythos-repair",
    "mythos-verify",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def default_validator(relative: str) -> Path:
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return home / "skills" / ".system" / relative


def clean_output(value: str | None, root: Path) -> str:
    text = (value or "").replace(str(root), "<suite-root>")
    return text.strip()[-4000:]


def run_check(
    *,
    check_id: str,
    validator_id: str,
    command: list[str],
    target: Path,
    root: Path,
) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=root,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=120,
        check=False,
    )
    return {
        "id": check_id,
        "validator": validator_id,
        "target": target.relative_to(root).as_posix(),
        "returncode": completed.returncode,
        "stdout": clean_output(completed.stdout, root),
        "stderr": clean_output(completed.stderr, root),
    }


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--skill-validator",
        type=Path,
        default=default_validator("skill-creator/scripts/quick_validate.py"),
    )
    parser.add_argument(
        "--codex-plugin-validator",
        type=Path,
        default=default_validator("plugin-creator/scripts/validate_plugin.py"),
    )
    parser.add_argument("--claude-executable", default=shutil.which("claude") or "")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/results/official-validation.json"),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    skill_validator = args.skill_validator.expanduser().resolve(strict=False)
    codex_validator = args.codex_plugin_validator.expanduser().resolve(strict=False)
    failures: list[str] = []
    for label, path in (
        ("OpenAI Skill validator", skill_validator),
        ("OpenAI Codex plugin validator", codex_validator),
    ):
        if not path.is_file():
            failures.append(f"{label} not found: {path}")
    claude = str(args.claude_executable).strip()
    if not claude:
        failures.append("Claude Code executable was not found; pass --claude-executable")
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 2

    checks: list[dict[str, Any]] = []
    for skill in SKILLS:
        target = root / "src" / "shared" / "skills" / skill
        checks.append(run_check(
            check_id=f"skill:{skill}",
            validator_id="openai-skill-creator-quick-validate",
            command=[sys.executable, str(skill_validator), str(target)],
            target=target,
            root=root,
        ))
    for label, target in (
        ("codex-plugin:dist", root / "dist" / "codex" / SUITE),
        (
            "codex-plugin:marketplace",
            root / "marketplaces" / "codex" / "plugins" / SUITE,
        ),
    ):
        checks.append(run_check(
            check_id=label,
            validator_id="openai-plugin-creator-validate-plugin",
            command=[sys.executable, str(codex_validator), str(target)],
            target=target,
            root=root,
        ))
    for label, target in (
        ("claude-plugin:dist", root / "dist" / "claude" / SUITE),
        ("claude-plugin:marketplace", root / "marketplaces" / "claude" / "plugins" / SUITE),
    ):
        checks.append(run_check(
            check_id=label,
            validator_id="claude-code-plugin-validate",
            command=[claude, "plugin", "validate", str(target)],
            target=target,
            root=root,
        ))

    version = subprocess.run(
        [claude, "--version"],
        cwd=root,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )
    binding_paths = [
        *(root / "src" / "shared" / "skills" / skill / "SKILL.md" for skill in SKILLS),
        root / "src" / "codex" / SUITE / ".codex-plugin" / "plugin.json",
        root / "src" / "claude" / SUITE / ".claude-plugin" / "plugin.json",
        root / "dist" / "codex" / SUITE / "build-manifest.json",
        root / "dist" / "claude" / SUITE / "build-manifest.json",
        root / "marketplaces" / "codex" / ".agents" / "plugins" / "marketplace.json",
        root / "marketplaces" / "claude" / ".claude-plugin" / "marketplace.json",
        root / "scripts" / "validate_official.py",
    ]
    missing = [path for path in binding_paths if not path.is_file()]
    failed = [check for check in checks if check["returncode"] != 0]
    status = "PASS" if not missing and not failed and version.returncode == 0 else "FAIL"
    payload = {
        "schema_version": 1,
        "suite": SUITE,
        "status": status,
        "validated_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "python_version": sys.version.split()[0],
        "validators": {
            "openai_skill_validator_sha256": sha256(skill_validator),
            "openai_codex_plugin_validator_sha256": sha256(codex_validator),
            "claude_code_version": clean_output(version.stdout or version.stderr, root),
        },
        "checks": checks,
        "bindings": {
            path.relative_to(root).as_posix(): sha256(path)
            for path in binding_paths
            if path.is_file()
        },
        "missing_bindings": [path.relative_to(root).as_posix() for path in missing],
    }
    atomic_json(output, payload)
    if status != "PASS":
        for check in failed:
            print(f"ERROR: {check['id']} failed: {check['stderr'] or check['stdout']}", file=sys.stderr)
        for path in missing:
            print(f"ERROR: Missing binding: {path}", file=sys.stderr)
        if version.returncode != 0:
            print("ERROR: claude --version failed", file=sys.stderr)
        return 1
    print(f"Official validator evidence passed and was written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
