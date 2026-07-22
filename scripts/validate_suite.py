#!/usr/bin/env python3
"""Run deterministic structural and language checks for the suite."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_evals import verify as verify_evaluations


HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
UNRESOLVED = re.compile(r"\b" + "TO" + r"DO\b|\b" + "FIX" + r"ME\b|\[" + "TO" + "DO|place" + r"holder", re.IGNORECASE)
TEXT_SUFFIXES = {".md", ".json", ".yaml", ".yml", ".py", ".toml", ".txt", ".rules", ".sh", ".cmd", ".ps1"}
SKILLS = {
    "mythos-orchestrate", "mythos-discover", "mythos-options", "mythos-plan",
    "mythos-build", "mythos-debug", "mythos-repair", "mythos-verify", "mythos-explain",
}


def validate_frontmatter(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return [f"Missing YAML frontmatter: {path}"]
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return [f"Unclosed YAML frontmatter: {path}"]
    keys = []
    for line in parts[1].splitlines():
        if line and not line.startswith((" ", "\t", "#")) and ":" in line:
            keys.append(line.split(":", 1)[0].strip())
    if keys != ["name", "description"]:
        errors.append(f"Frontmatter must contain only name and description in order: {path} ({keys})")
    return errors


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def _source_inventory(root: Path, host: str) -> dict[str, str]:
    """Return the exact package inventory expected from canonical sources."""
    suite = "mythos-5-burning-art"
    result: dict[str, str] = {}
    host_root = root / "src" / host / suite
    for path in sorted(item for item in host_root.rglob("*") if item.is_file()):
        if "__pycache__" not in path.parts and path.suffix != ".pyc":
            result[path.relative_to(host_root).as_posix()] = sha256(path)
    skills = root / "src" / "shared" / "skills"
    for path in sorted(item for item in skills.rglob("*") if item.is_file()):
        relative = path.relative_to(skills)
        if host == "claude" and "agents" in relative.parts:
            continue
        if "__pycache__" not in relative.parts and path.suffix != ".pyc":
            result[(Path("skills") / relative).as_posix()] = sha256(path)
    runtime = root / "src" / "shared" / "runtime"
    for path in sorted(item for item in runtime.rglob("*") if item.is_file()):
        relative = path.relative_to(runtime)
        if "__pycache__" not in relative.parts and path.suffix != ".pyc":
            result[(Path("scripts") / relative).as_posix()] = sha256(path)
    return result


def validate_source_parity(root: Path, host: str, package: Path) -> list[str]:
    expected = _source_inventory(root, host)
    actual = {
        path.relative_to(package).as_posix(): sha256(path)
        for path in sorted(item for item in package.rglob("*") if item.is_file())
        if path.name != "build-manifest.json"
    }
    if expected == actual:
        return []
    missing = sorted(set(expected).difference(actual))
    extra = sorted(set(actual).difference(expected))
    stale = sorted(path for path in set(expected).intersection(actual) if expected[path] != actual[path])
    return [
        f"Source-to-distribution parity failed for {host}: "
        f"missing={missing}, extra={extra}, stale={stale}"
    ]


def validate_build_manifest(package: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = package / "build-manifest.json"
    if not manifest_path.is_file():
        return [f"Missing build manifest: {manifest_path}"]
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {item["path"]: item for item in payload.get("files", [])}
    actual = {
        path.relative_to(package).as_posix(): path
        for path in sorted(item for item in package.rglob("*") if item.is_file() and item != manifest_path)
    }
    if set(expected) != set(actual):
        errors.append(f"Build manifest inventory mismatch: {package}")
        return errors
    for relative, path in actual.items():
        record = expected[relative]
        if record.get("sha256") != sha256(path) or record.get("bytes") != path.stat().st_size:
            errors.append(f"Build manifest digest mismatch: {path}")
    return errors


def validate_schema_meta(schema: object, path: Path, pointer: str = "$") -> list[str]:
    """Check high-value JSON Schema keyword shapes without external packages."""
    errors: list[str] = []
    if isinstance(schema, dict):
        for keyword in ("allOf", "anyOf", "oneOf", "prefixItems"):
            if keyword in schema and not isinstance(schema[keyword], list):
                errors.append(f"JSON Schema {keyword} must be an array: {path} at {pointer}")
        if "required" in schema and (
            not isinstance(schema["required"], list)
            or not all(isinstance(item, str) for item in schema["required"])
        ):
            errors.append(f"JSON Schema required must be a string array: {path} at {pointer}")
        for keyword in ("properties", "patternProperties", "$defs", "dependentSchemas"):
            if keyword in schema and not isinstance(schema[keyword], dict):
                errors.append(f"JSON Schema {keyword} must be an object: {path} at {pointer}")
        for key, value in schema.items():
            errors.extend(validate_schema_meta(value, path, f"{pointer}/{key}"))
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            errors.extend(validate_schema_meta(value, path, f"{pointer}/{index}"))
    return errors


def validate_reviewer_receipt_schema(schema: object, path: Path) -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict) or not isinstance(schema.get("oneOf"), list):
        return [f"Reviewer receipt schema must define oneOf branches: {path}"]
    branches = {branch.get("title"): branch for branch in schema["oneOf"] if isinstance(branch, dict)}
    for title in ("Plan critic receipt", "Verifier receipt"):
        branch = branches.get(title)
        if not isinstance(branch, dict):
            errors.append(f"Missing reviewer receipt branch {title}: {path}")
            continue
        properties = branch.get("properties", {})
        if properties.get("verdict") != {"const": "PASS"}:
            errors.append(f"{title} must publish PASS as the only accepted receipt verdict: {path}")
        for field in ("blocking_findings", "high_findings", "context_contamination"):
            definition = properties.get(field, {})
            if definition.get("type") != "array" or definition.get("maxItems") != 0:
                errors.append(f"{title} {field} must be an explicit empty array for PASS: {path}")
        if title == "Verifier receipt":
            for field in ("scope_matches_approval", "approval_current"):
                if properties.get(field) != {"const": True}:
                    errors.append(f"Verifier receipt {field} must be true for PASS: {path}")
    return errors

def validate_plugin_manifest(path: Path, host: str) -> list[str]:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"Invalid {host} plugin manifest {path}: {exc}"]
    required = {"name", "version", "description", "author", "keywords"}
    missing = sorted(required.difference(payload)) if isinstance(payload, dict) else sorted(required)
    if not isinstance(payload, dict) or missing:
        return [f"{host} plugin manifest lacks required fields {missing}: {path}"]
    if payload.get("name") != "mythos-5-burning-art":
        errors.append(f"{host} plugin manifest has the wrong name: {path}")
    if not isinstance(payload.get("version"), str) or re.fullmatch(r"\d+\.\d+\.\d+", payload["version"]) is None:
        errors.append(f"{host} plugin manifest version is not semantic: {path}")
    if not isinstance(payload.get("description"), str) or not payload["description"].strip():
        errors.append(f"{host} plugin manifest description is empty: {path}")
    author = payload.get("author")
    if not isinstance(author, dict) or not isinstance(author.get("name"), str) or not author["name"].strip():
        errors.append(f"{host} plugin manifest author is invalid: {path}")
    keywords = payload.get("keywords")
    if not isinstance(keywords, list) or not keywords or not all(isinstance(item, str) and item for item in keywords):
        errors.append(f"{host} plugin manifest keywords are invalid: {path}")
    if host == "codex":
        if payload.get("skills") != "./skills/" or not isinstance(payload.get("interface"), dict):
            errors.append(f"Codex plugin manifest lacks skills or interface metadata: {path}")
    elif not isinstance(payload.get("userConfig"), dict):
        errors.append(f"Claude plugin manifest lacks userConfig: {path}")
    return errors


def validate_codex_marketplace(root: Path) -> list[str]:
    market_root = (root / "marketplaces" / "codex").resolve()
    catalog = market_root / ".agents" / "plugins" / "marketplace.json"
    if not catalog.is_file():
        return [f"Missing Codex marketplace catalog: {catalog}"]
    try:
        payload = json.loads(catalog.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"Invalid Codex marketplace catalog {catalog}: {exc}"]
    errors: list[str] = []
    plugins = payload.get("plugins") if isinstance(payload, dict) else None
    if not isinstance(plugins, list) or len(plugins) != 1 or not isinstance(plugins[0], dict):
        return [f"Codex marketplace must contain exactly one plugin entry: {catalog}"]
    entry = plugins[0]
    source = entry.get("source")
    if entry.get("name") != "mythos-5-burning-art" or not isinstance(source, dict):
        return [f"Codex marketplace plugin entry is invalid: {catalog}"]
    declared = source.get("path")
    if source.get("source") != "local" or not isinstance(declared, str) or not declared.strip():
        return [f"Codex marketplace local source is invalid: {catalog}"]
    declared_path = Path(declared)
    if declared_path.is_absolute():
        return [f"Codex marketplace source must be marketplace-root-relative: {catalog}"]
    resolved = (market_root / declared_path).resolve()
    try:
        resolved.relative_to(market_root)
    except ValueError:
        return [f"Codex marketplace source escapes the marketplace root: {catalog}"]
    if resolved != market_root / "plugins" / "mythos-5-burning-art":
        errors.append(f"Codex marketplace source resolves to an unexpected path: {resolved}")
    if not resolved.is_dir():
        errors.append(f"Codex marketplace source does not resolve to a package: {resolved}")
    elif not (resolved / ".codex-plugin" / "plugin.json").is_file():
        errors.append(f"Codex marketplace source lacks a plugin manifest: {resolved}")
    return errors
def validate_official_evidence(root: Path) -> list[str]:
    path = root / "evals" / "results" / "official-validation.json"
    if not path.is_file():
        return [f"Missing official validator evidence: {path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"Invalid official validator evidence {path}: {exc}"]
    errors: list[str] = []
    if payload.get("schema_version") != 1 or payload.get("suite") != "mythos-5-burning-art" or payload.get("status") != "PASS":
        errors.append(f"Official validator evidence is not a PASS for this suite: {path}")
    expected_targets = {
        **{f"skill:{skill}": f"src/shared/skills/{skill}" for skill in SKILLS},
        "codex-plugin:dist": "dist/codex/mythos-5-burning-art",
        "codex-plugin:marketplace": "marketplaces/codex/plugins/mythos-5-burning-art",
        "claude-plugin:dist": "dist/claude/mythos-5-burning-art",
        "claude-plugin:marketplace": "marketplaces/claude/plugins/mythos-5-burning-art",
    }
    expected_checks = set(expected_targets)
    checks = payload.get("checks")
    if not isinstance(checks, list):
        errors.append(f"Official validator checks must be an array: {path}")
    else:
        identifiers = [item.get("id") for item in checks if isinstance(item, dict)]
        if set(identifiers) != expected_checks or len(identifiers) != len(expected_checks):
            errors.append(f"Official validator check coverage mismatch: {path}")
        for item in checks:
            if not isinstance(item, dict) or item.get("returncode") != 0:
                errors.append(f"Official validator check did not pass: {item}")
                continue
            expected_target = expected_targets.get(item.get("id"))
            if expected_target is not None and item.get("target") != expected_target:
                errors.append(f"Official validator check targeted the wrong path: {item}")
    validators = payload.get("validators")
    if not isinstance(validators, dict):
        errors.append(f"Official validator identities are missing: {path}")
    else:
        for key in ("openai_skill_validator_sha256", "openai_codex_plugin_validator_sha256"):
            value = validators.get(key)
            if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
                errors.append(f"Official validator digest is invalid for {key}: {path}")
        if not isinstance(validators.get("claude_code_version"), str) or not validators["claude_code_version"].strip():
            errors.append(f"Claude Code validator version is missing: {path}")
    bindings = payload.get("bindings")
    if not isinstance(bindings, dict):
        return errors + [f"Official validator bindings are missing: {path}"]
    required_bindings = {
        *(f"src/shared/skills/{skill}/SKILL.md" for skill in SKILLS),
        "src/codex/mythos-5-burning-art/.codex-plugin/plugin.json",
        "src/claude/mythos-5-burning-art/.claude-plugin/plugin.json",
        "dist/codex/mythos-5-burning-art/build-manifest.json",
        "dist/claude/mythos-5-burning-art/build-manifest.json",
        "marketplaces/codex/.agents/plugins/marketplace.json",
        "marketplaces/claude/.claude-plugin/marketplace.json",
        "scripts/validate_official.py",
    }
    if set(bindings) != required_bindings:
        errors.append(f"Official validator binding coverage mismatch: {path}")
    for relative, expected in bindings.items():
        target = root / relative
        if not target.is_file() or not isinstance(expected, str) or sha256(target) != expected:
            errors.append(f"Official validator evidence is stale for {relative}: {path}")
    if payload.get("missing_bindings") != []:
        errors.append(f"Official validator evidence reports missing bindings: {path}")
    return errors

def validate(root: Path) -> list[str]:
    errors: list[str] = []
    root = root.resolve()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            errors.append(f"Generated Python cache is prohibited in the release tree: {path}")
            continue
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if path.parent == root / "spec" and path.name.endswith(".schema.json"):
                    errors.extend(validate_schema_meta(payload, path))
                    if path.name == "reviewer-receipt.schema.json":
                        errors.extend(validate_reviewer_receipt_schema(payload, path))
            except Exception as exc:
                errors.append(f"Invalid JSON {path}: {exc}")
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"AGENTS.md", "CLAUDE.md", "SKILL.md"}:
            text = path.read_text(encoding="utf-8")
            if UNRESOLVED.search(text):
                errors.append(f"Unresolved scaffold marker in {path}")
            if path != root / "README.md" and HAN.search(text):
                errors.append(f"Non-English Han character in {path}")
    canonical = root / "src" / "shared" / "skills"
    found = {path.name for path in canonical.iterdir() if path.is_dir()} if canonical.exists() else set()
    if found != SKILLS:
        errors.append(f"Canonical skill set mismatch: expected {sorted(SKILLS)}, found {sorted(found)}")
    for skill in sorted(found):
        skill_file = canonical / skill / "SKILL.md"
        if not skill_file.is_file():
            errors.append(f"Missing SKILL.md: {skill}")
        else:
            errors.extend(validate_frontmatter(skill_file))
        if (canonical / skill / "README.md").exists():
            errors.append(f"Skill contains prohibited README.md: {skill}")
    for host, manifest in [
        ("codex", root / "src" / "codex" / "mythos-5-burning-art" / ".codex-plugin" / "plugin.json"),
        ("claude", root / "src" / "claude" / "mythos-5-burning-art" / ".claude-plugin" / "plugin.json"),
    ]:
        if not manifest.is_file():
            errors.append(f"Missing plugin manifest: {manifest}")
        else:
            errors.extend(validate_plugin_manifest(manifest, host))
    if not (root / "README.md").is_file():
        errors.append("Missing root README.md")
    errors.extend(verify_evaluations(root))
    errors.extend(validate_codex_marketplace(root))
    errors.extend(validate_official_evidence(root))

    codex_dist = root / "dist" / "codex" / "mythos-5-burning-art"
    claude_dist = root / "dist" / "claude" / "mythos-5-burning-art"
    for host, package in (("codex", codex_dist), ("claude", claude_dist)):
        if package.is_dir():
            errors.extend(validate_build_manifest(package))
            errors.extend(validate_source_parity(root, host, package))
        else:
            errors.append(f"Missing distribution package: {package}")

    marketplace_pairs = (
        (codex_dist, root / "marketplaces" / "codex" / "plugins" / "mythos-5-burning-art"),
        (claude_dist, root / "marketplaces" / "claude" / "plugins" / "mythos-5-burning-art"),
    )
    for package, marketplace_copy in marketplace_pairs:
        if not marketplace_copy.is_dir():
            errors.append(f"Missing marketplace package: {marketplace_copy}")
        elif package.is_dir() and inventory(package) != inventory(marketplace_copy):
            errors.append(f"Marketplace package is stale: {marketplace_copy}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = validate(args.root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Suite structure and language checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




