from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "scripts" / "install_repo_adapter.py"
UNINSTALL = ROOT / "scripts" / "uninstall_repo_adapter.py"
BEGIN = "<!-- MYTHOS-5-BURNING-ART:BEGIN -->"


class RepositoryAdapterContractTests(unittest.TestCase):
    TEMP_ROOT = ROOT / ".adapter-test-tmp"

    @classmethod
    def setUpClass(cls) -> None:
        cls.TEMP_ROOT.mkdir(exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.TEMP_ROOT.exists() and not any(cls.TEMP_ROOT.iterdir()):
            cls.TEMP_ROOT.rmdir()

    def run_script(
        self,
        script: Path,
        *arguments: str,
        success: bool = True,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        process_environment = os.environ.copy()
        if environment:
            process_environment.update(environment)
        result = subprocess.run(
            [sys.executable, str(script), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            env=process_environment,
        )
        if success and result.returncode != 0:
            self.fail(f"Command failed: {result.stderr}\n{result.stdout}")
        if not success and result.returncode == 0:
            self.fail(f"Command unexpectedly succeeded: {result.stdout}")
        return result

    def install(
        self,
        repo: Path,
        host: str,
        apply: bool = True,
        success: bool = True,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        arguments = ["--root", str(ROOT), "--repo", str(repo), "--host", host]
        if apply:
            arguments.append("--apply")
        return self.run_script(INSTALL, *arguments, success=success, environment=environment)

    def uninstall(
        self,
        repo: Path,
        host: str,
        apply: bool = True,
        success: bool = True,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        arguments = ["--repo", str(repo), "--host", host]
        if apply:
            arguments.append("--apply")
        return self.run_script(UNINSTALL, *arguments, success=success, environment=environment)

    def exercise_order(self, order: tuple[str, str], interrupt_first: bool = False) -> None:
        with tempfile.TemporaryDirectory(prefix="mythos-adapter-", dir=self.TEMP_ROOT) as temporary:
            repo = Path(temporary)
            original_agents = b"# User AGENTS\r\n\r\nKeep trailing spaces.  \r\n"
            original_claude = b"# User CLAUDE\n\nUser content stays byte-exact.\n"
            (repo / "AGENTS.md").write_bytes(original_agents)
            (repo / "CLAUDE.md").write_bytes(original_claude)

            self.install(repo, "codex", apply=False)
            self.assertEqual((repo / "AGENTS.md").read_bytes(), original_agents)
            self.assertFalse((repo / ".mythos-adapter-install-codex.json").exists())

            self.install(repo, "codex")
            self.install(repo, "claude")
            self.assertEqual((repo / "AGENTS.md").read_text(encoding="utf-8").count(BEGIN), 1)
            self.assertEqual((repo / "CLAUDE.md").read_text(encoding="utf-8").count(BEGIN), 1)
            self.assertTrue((repo / ".codex" / "agents" / "mythos-plan-critic.toml").is_file())
            self.assertTrue((repo / ".claude" / "rules" / "mythos-lifecycle.md").is_file())

            self.uninstall(repo, order[0], apply=False)
            self.assertTrue((repo / f".mythos-adapter-install-{order[0]}.json").exists())
            if interrupt_first:
                result = self.uninstall(
                    repo,
                    order[0],
                    success=False,
                    environment={"MYTHOS_ADAPTER_TEST_FAIL_UNINSTALL_AFTER": "1"},
                )
                self.assertIn("Simulated mid-uninstall failure", result.stderr)
                self.assertTrue((repo / f".mythos-adapter-install-{order[0]}.json").exists())
            self.uninstall(repo, order[0])
            self.uninstall(repo, order[1])

            self.assertEqual((repo / "AGENTS.md").read_bytes(), original_agents)
            self.assertEqual((repo / "CLAUDE.md").read_bytes(), original_claude)
            self.assertFalse((repo / ".codex" / "agents" / "mythos-plan-critic.toml").exists())
            self.assertFalse((repo / ".claude" / "rules" / "mythos-lifecycle.md").exists())
            self.assertFalse((repo / ".codex").exists())
            self.assertFalse((repo / ".claude").exists())
            self.assertFalse((repo / ".mythos-adapter-install-codex.json").exists())
            self.assertFalse((repo / ".mythos-adapter-install-claude.json").exists())

    def make_directory_redirect(self, link: Path, target: Path) -> bool:
        try:
            link.symlink_to(target, target_is_directory=True)
            return True
        except (NotImplementedError, OSError):
            if os.name != "nt":
                return False
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0 and link.exists()

    def test_claude_only_does_not_install_codex_agent_definitions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mythos-adapter-", dir=self.TEMP_ROOT) as temporary:
            repo = Path(temporary)
            self.install(repo, "claude")
            self.assertTrue((repo / "AGENTS.md").is_file())
            self.assertTrue((repo / "CLAUDE.md").is_file())
            self.assertTrue((repo / ".claude" / "rules" / "mythos-lifecycle.md").is_file())
            self.assertFalse((repo / ".codex").exists())
            self.uninstall(repo, "claude")
            self.assertFalse((repo / "AGENTS.md").exists())
            self.assertFalse((repo / "CLAUDE.md").exists())
            self.assertFalse((repo / ".claude").exists())

    def test_uninstall_codex_then_claude_transfers_shared_ownership(self) -> None:
        self.exercise_order(("codex", "claude"))

    def test_uninstall_claude_then_codex_preserves_original_guidance(self) -> None:
        self.exercise_order(("claude", "codex"))

    def test_mid_install_failure_rolls_back_exactly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mythos-adapter-", dir=self.TEMP_ROOT) as temporary:
            repo = Path(temporary)
            original = b"# Existing\r\n\r\nDo not normalize me.  \r\n"
            (repo / "AGENTS.md").write_bytes(original)
            result = self.install(
                repo,
                "codex",
                success=False,
                environment={"MYTHOS_ADAPTER_TEST_FAIL_INSTALL_AFTER": "2"},
            )
            self.assertIn("Simulated mid-install failure", result.stderr)
            self.assertEqual((repo / "AGENTS.md").read_bytes(), original)
            self.assertEqual({path.name for path in repo.iterdir()}, {"AGENTS.md"})
            self.assertFalse((repo / ".mythos-adapter-install-codex.json").exists())

    def test_partial_uninstall_is_resumable_in_either_host_order(self) -> None:
        for order in (("codex", "claude"), ("claude", "codex")):
            with self.subTest(order=order):
                self.exercise_order(order, interrupt_first=True)

    def test_partial_transfer_survives_opposite_host_uninstall(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mythos-adapter-", dir=self.TEMP_ROOT) as temporary:
            repo = Path(temporary)
            original_agents = b"# Original AGENTS\r\n"
            original_claude = b"# Original CLAUDE\n"
            (repo / "AGENTS.md").write_bytes(original_agents)
            (repo / "CLAUDE.md").write_bytes(original_claude)
            self.install(repo, "codex")
            self.install(repo, "claude")

            payload = json.loads((repo / ".mythos-adapter-install-codex.json").read_text(encoding="utf-8"))
            mutation_count = 0
            for entry in reversed(payload["changes"]):
                if entry["owned"]:
                    mutation_count += 1
                if entry["path"] == "AGENTS.md":
                    break
            result = self.uninstall(
                repo,
                "codex",
                success=False,
                environment={"MYTHOS_ADAPTER_TEST_FAIL_UNINSTALL_AFTER": str(mutation_count)},
            )
            self.assertIn("Simulated mid-uninstall failure", result.stderr)

            claude_payload = json.loads((repo / ".mythos-adapter-install-claude.json").read_text(encoding="utf-8"))
            claude_agents = next(entry for entry in claude_payload["changes"] if entry["path"] == "AGENTS.md")
            self.assertTrue(claude_agents["owned"])

            self.uninstall(repo, "claude")
            self.uninstall(repo, "codex")
            self.assertEqual((repo / "AGENTS.md").read_bytes(), original_agents)
            self.assertEqual((repo / "CLAUDE.md").read_bytes(), original_claude)
    def test_uninstall_refuses_modified_owned_content(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mythos-adapter-", dir=self.TEMP_ROOT) as temporary:
            repo = Path(temporary)
            self.install(repo, "codex")
            agent = repo / ".codex" / "agents" / "mythos-plan-critic.toml"
            agent.write_text(agent.read_text(encoding="utf-8") + "\n# user modification\n", encoding="utf-8")
            result = self.uninstall(repo, "codex", success=False)
            self.assertIn("Refusing to alter modified adapter content", result.stderr)
            self.assertTrue(agent.exists())
            self.assertTrue((repo / ".mythos-adapter-install-codex.json").exists())

    def test_preexisting_redirect_cannot_escape_repository(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mythos-adapter-", dir=self.TEMP_ROOT) as temporary:
            base = Path(temporary)
            repo = base / "repo"
            outside = base / "outside"
            repo.mkdir()
            outside.mkdir()
            original = b"# Existing AGENTS\n"
            (repo / "AGENTS.md").write_bytes(original)
            if not self.make_directory_redirect(repo / ".codex", outside):
                self.skipTest("The operating system cannot create a directory symlink or junction")
            result = self.install(repo, "codex", success=False)
            self.assertIn("symlink, junction, or reparse point", result.stderr)
            self.assertEqual((repo / "AGENTS.md").read_bytes(), original)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertFalse((repo / ".mythos-adapter-install-codex.json").exists())

    def test_atomic_write_interruption_preserves_prior_bytes(self) -> None:
        spec = importlib.util.spec_from_file_location("mythos_install_adapter_test", INSTALL)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="mythos-adapter-", dir=self.TEMP_ROOT) as temporary:
            repo = Path(temporary).resolve()
            destination = repo / "AGENTS.md"
            destination.write_bytes(b"prior-bytes")
            with mock.patch.object(module.os, "replace", side_effect=RuntimeError("injected replace interruption")):
                with self.assertRaisesRegex(RuntimeError, "injected replace interruption"):
                    module.atomic_write_bytes(repo, destination, b"new-bytes")
            self.assertEqual(destination.read_bytes(), b"prior-bytes")
            self.assertEqual(list(repo.glob(".AGENTS.md.*.tmp")), [])

    def test_concurrent_cross_host_install_is_serialized(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mythos-adapter-", dir=self.TEMP_ROOT) as temporary:
            repo = Path(temporary)
            commands = [
                [sys.executable, str(INSTALL), "--root", str(ROOT), "--repo", str(repo), "--host", host, "--apply"]
                for host in ("codex", "claude")
            ]
            processes = [
                subprocess.Popen(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for command in commands
            ]
            results = [process.communicate(timeout=60) for process in processes]
            for process, (stdout, stderr) in zip(processes, results):
                self.assertEqual(process.returncode, 0, f"{stderr} | {stdout}")
            self.assertEqual((repo / "AGENTS.md").read_text(encoding="utf-8").count(BEGIN), 1)
            self.uninstall(repo, "codex")
            self.uninstall(repo, "claude")
            self.assertFalse((repo / "AGENTS.md").exists())

if __name__ == "__main__":
    unittest.main()