#!/usr/bin/env python3
"""Build deterministic Codex and Claude Code packages from canonical sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


SUITE = "mythos-5-burning-art"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def safe_replace_dir(path: Path, root: Path) -> None:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved == root_resolved or root_resolved not in resolved.parents:
        raise RuntimeError(f"Refusing to replace path outside build root: {resolved}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(source)
    shutil.copytree(source, destination, dirs_exist_ok=True)


def remove_skill_ui_metadata(package_skills: Path) -> None:
    for metadata in package_skills.glob("*/agents"):
        if metadata.is_dir():
            shutil.rmtree(metadata)


def write_build_manifest(package: Path, host: str) -> None:
    files = []
    for path in sorted(p for p in package.rglob("*") if p.is_file()):
        if path.name == "build-manifest.json":
            continue
        files.append({
            "path": path.relative_to(package).as_posix(),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        })
    payload = {
        "schema_version": 1,
        "suite": SUITE,
        "host": host,
        "generated": True,
        "files": files,
    }
    (package / "build-manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def build(root: Path) -> None:
    root = root.resolve()
    shared_skills = root / "src" / "shared" / "skills"
    runtime = root / "src" / "shared" / "runtime"
    dist_root = root / "dist"
    codex_out = dist_root / "codex" / SUITE
    claude_out = dist_root / "claude" / SUITE

    safe_replace_dir(codex_out, root)
    safe_replace_dir(claude_out, root)

    codex_source = root / "src" / "codex" / SUITE
    claude_source = root / "src" / "claude" / SUITE
    copy_tree(codex_source, codex_out)
    copy_tree(claude_source, claude_out)
    copy_tree(shared_skills, codex_out / "skills")
    copy_tree(shared_skills, claude_out / "skills")
    remove_skill_ui_metadata(claude_out / "skills")
    copy_tree(runtime, codex_out / "scripts")
    copy_tree(runtime, claude_out / "scripts")

    for path in list(codex_out.rglob("__pycache__")) + list(claude_out.rglob("__pycache__")):
        shutil.rmtree(path)
    for path in list(codex_out.rglob("*.pyc")) + list(claude_out.rglob("*.pyc")):
        path.unlink()

    write_build_manifest(codex_out, "codex")
    write_build_manifest(claude_out, "claude-code")

    codex_market_root = root / "marketplaces" / "codex"
    codex_catalog_root = codex_market_root / ".agents" / "plugins"
    claude_market_root = root / "marketplaces" / "claude"
    safe_replace_dir(codex_market_root, root)
    safe_replace_dir(claude_market_root, root)
    codex_catalog_root.mkdir(parents=True, exist_ok=True)
    (codex_market_root / "plugins").mkdir(parents=True, exist_ok=True)
    (claude_market_root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (claude_market_root / "plugins").mkdir(parents=True, exist_ok=True)
    copy_tree(codex_out, codex_market_root / "plugins" / SUITE)
    copy_tree(claude_out, claude_market_root / "plugins" / SUITE)
    codex_marketplace = {
        "name": "mythos-5-burning-art-local",
        "interface": {"displayName": "Mythos 5 Burning Art Local"},
        "plugins": [{
            "name": SUITE,
            "source": {"source": "local", "path": f"./plugins/{SUITE}"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Developer Tools",
        }],
    }
    claude_marketplace = {
        "name": "mythos-5-burning-art-local",
        "owner": {"name": "Mythos 5 Burning Art Project"},
        "metadata": {"description": "Local portable distribution of the Mythos 5 Burning Art workflow suite."},
        "plugins": [{
            "name": SUITE,
            "source": f"./plugins/{SUITE}",
            "description": "A governed coding workflow with plan approval, independent review, and durable loops.",
            "version": "0.1.0",
            "author": {"name": "Mythos 5 Burning Art Project"},
        }],
    }
    (codex_catalog_root / "marketplace.json").write_text(
        json.dumps(codex_marketplace, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (claude_market_root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(claude_marketplace, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    build(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



