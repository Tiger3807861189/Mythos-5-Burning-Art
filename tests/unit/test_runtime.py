from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "src" / "shared" / "runtime"
sys.path.insert(0, str(RUNTIME))

from mythos_runtime.approval import AuthorityStore, approval_syntax, observe_human_event
from mythos_runtime.canonical import canonical_json, compute_base_fingerprint, normalize_path_text, plan_material, project_content_manifest
from mythos_runtime.lifecycle import LifecycleError, Phase, PhaseStatus, TerminalState, validate_transition
from mythos_runtime.hooks import _read_only_exempt
from mythos_runtime.locking import FileLock
from mythos_runtime.policy import (
    Decision, approved_scope_contains_paths, approved_scope_is_safe, approved_tool_guard, classify_tool,
)
from mythos_runtime.state import RuntimeStore
from mythos_runtime.storage import EventLog, IntegrityError


class CanonicalTests(unittest.TestCase):
    def test_unicode_lf_sorted_and_windows_path(self) -> None:
        composed = canonical_json({"z": "e\u0301\r\nnext", "a": 1}).decode("utf-8")
        self.assertEqual(composed, '{"a":1,"z":"é\\nnext"}')
        self.assertEqual(
            normalize_path_text(r"C:\Users\WIKI\My Project\Delta-Case", platform="windows"),
            "c:/users/wiki/my project/delta-case",
        )

    def test_git_fingerprint_changes_when_untracked_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run(["git", "init", "--quiet", str(root)], capture_output=True, check=False)
            if result.returncode:
                self.skipTest("git is unavailable")
            path = root / "untracked.txt"
            path.write_text("first", encoding="utf-8")
            first = compute_base_fingerprint(root)
            path.write_text("second", encoding="utf-8")
            second = compute_base_fingerprint(root)
            self.assertNotEqual(first, second)

    def test_git_fingerprint_excludes_ignored_content_but_scoped_manifest_tracks_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run(["git", "init", "--quiet", str(root)], capture_output=True, check=False)
            if result.returncode:
                self.skipTest("git is unavailable")
            (root / ".gitignore").write_text("generated/\n", encoding="utf-8")
            generated = root / "generated"
            generated.mkdir()
            path = generated / "artifact.bin"
            path.write_bytes(b"first")
            first = compute_base_fingerprint(root)
            scoped_first = project_content_manifest(root, include_paths=("generated/",))
            path.write_bytes(b"second")
            second = compute_base_fingerprint(root)
            scoped_second = project_content_manifest(root, include_paths=("generated/",))
            self.assertEqual(first, second)
            self.assertNotEqual(scoped_first, scoped_second)

    def test_command_sensitive_manifest_tracks_default_generated_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "node_modules"
            generated.mkdir()
            artifact = generated / "artifact.bin"
            artifact.write_bytes(b"first")
            bounded_first = project_content_manifest(root)
            complete_first = project_content_manifest(root, include_generated=True)
            artifact.write_bytes(b"second")
            bounded_second = project_content_manifest(root)
            complete_second = project_content_manifest(root, include_generated=True)
            self.assertEqual(bounded_first, bounded_second)
            self.assertNotEqual(complete_first, complete_second)

    def test_unborn_tracked_same_size_modification_changes_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run(["git", "init", "--quiet", str(root)], capture_output=True, check=False)
            if result.returncode:
                self.skipTest("git is unavailable")
            path = root / "tracked.txt"
            path.write_text("AAAA", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True, capture_output=True)
            first = compute_base_fingerprint(root)
            path.write_text("BBBB", encoding="utf-8")
            second = compute_base_fingerprint(root)
            self.assertNotEqual(first, second)

class LifecycleTests(unittest.TestCase):
    def test_material_unknown_can_force_replanning_from_execution_or_verification(self) -> None:
        validate_transition(
            Phase.IMPLEMENTATION_LOOP,
            Phase.UNKNOWNS_AND_BLINDSPOTS,
            approval_valid=False,
        )
        validate_transition(
            Phase.INDEPENDENT_VERIFICATION,
            Phase.UNKNOWNS_AND_BLINDSPOTS,
            approval_valid=False,
        )


class PolicyTests(unittest.TestCase):
    def test_read_only_shell_options_cannot_write_or_execute_filters(self) -> None:
        safe_command = "git --no-pager --no-optional-locks -c core.fsmonitor=false diff --no-ext-diff --no-textconv --stat --"
        safe = classify_tool("shell_command", {"command": safe_command})
        self.assertEqual(safe.decision, Decision.ALLOW)
        plain = classify_tool("shell_command", {"command": "git diff --stat"})
        self.assertEqual(plain.decision, Decision.NEEDS_HUMAN_JUDGMENT)
        for command in (
            "git diff --output=report.txt",
            "git diff --output report.txt",
            "git diff --ext-diff",
            "git show --textconv HEAD:file.txt",
            "rg --pre formatter needle .",
            "rg --pre-glob *.py needle .",
            "rg --generate man",
        ):
            with self.subTest(command=command):
                result = classify_tool("shell_command", {"command": command})
                self.assertEqual(result.decision, Decision.DENY)
                self.assertTrue(result.substantive)

    def test_current_codex_exec_command_maps_to_discovery_and_exact_command_policy(self) -> None:
        discovery = classify_tool("exec_command", {"cmd": "rg --files"})
        self.assertEqual(discovery.decision, Decision.ALLOW)
        blocked_preprocessor = classify_tool("exec_command", {"cmd": "rg --pre formatter needle ."})
        self.assertEqual(blocked_preprocessor.decision, Decision.DENY)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = "python -m unittest"
            approved = approved_tool_guard(
                tool_name="exec_command",
                tool_input={"cmd": command, "workdir": str(root)},
                project_root=root,
                scope={"paths": [], "commands": [command], "external_effects": []},
                invocation_root=root,
            )
            self.assertEqual(approved.decision, Decision.ALLOW)
            self.assertTrue(approved.substantive)
    def test_read_only_exemption_fails_closed_for_compound_mutations(self) -> None:
        self.assertTrue(_read_only_exempt("Explain what this repository is"))
        for prompt in (
            "Explain the file, then overwrite it",
            "Explain the file, then delete it",
            "Summarize the module and modify its imports",
            "Report status; truncate the log",
            "Answer what changed, then append a release note",
            "Explain the config and chmod the script",
        ):
            with self.subTest(prompt=prompt):
                self.assertFalse(_read_only_exempt(prompt))
    def test_read_only_wording_cannot_hide_mutation(self) -> None:
        for prompt in (
            "Summarize the repository by purging its cache.",
            "Report status by messaging Slack.",
            "Answer the question by notifying the team.",
            "Explain the file by obliterating it.",
        ):
            with self.subTest(prompt=prompt):
                self.assertFalse(_read_only_exempt(prompt))

    def test_exact_and_recursive_scope_semantics_and_unsafe_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "file.py").write_text("pass", encoding="utf-8")
            self.assertFalse(approved_scope_contains_paths(
                project_root=root, scope={"paths": ["src"]}, candidates=["src/file.py"]
            ))
            self.assertTrue(approved_scope_contains_paths(
                project_root=root, scope={"paths": ["src/"]}, candidates=["src/file.py"]
            ))
            linked = root / "src" / "linked.py"
            try:
                os.link(root / "src" / "file.py", linked)
            except OSError:
                pass
            else:
                self.assertFalse(approved_scope_contains_paths(
                    project_root=root, scope={"paths": ["src/"]}, candidates=["src/linked.py"]
                ))
            for unsafe in (str(root / "src"), "../outside", "CON.txt", "name:stream"):
                with self.subTest(scope=unsafe):
                    self.assertFalse(approved_scope_is_safe(
                        project_root=root, scope={"paths": [unsafe]}
                    ))

    def test_exact_shell_binding_rejects_near_matches_escape_workdir_and_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sub").mkdir()
            command = "python -B tools/check.py"
            scope = {"paths": ["report.json"], "commands": [command], "external_effects": []}
            allowed = approved_tool_guard(
                tool_name="shell_command", tool_input={"command": command, "workdir": str(root)},
                project_root=root, scope=scope, invocation_root=root,
            )
            self.assertEqual(allowed.decision, Decision.ALLOW)
            cases = (
                {"command": command + " --extra", "workdir": str(root)},
                {"command": command, "workdir": str(root / "sub")},
                {"command": command, "workdir": str(root), "env": {"MODE": "write"}},
                {"command": "python -B ../tools/check.py", "workdir": str(root)},
                {"command": "python -B C:\\outside\\check.py", "workdir": str(root)},
                {"command": "python -B /outside/check.py", "workdir": str(root)},
            )
            for tool_input in cases:
                with self.subTest(tool_input=tool_input):
                    result = approved_tool_guard(
                        tool_name="shell_command", tool_input=tool_input,
                        project_root=root, scope=scope, invocation_root=root,
                    )
                    self.assertEqual(result.decision, Decision.DENY)

    def test_apply_patch_move_and_unobservable_tools_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patch = "*** Begin Patch\n*** Update File: src/file.py\n*** Move to: ../outside.py\n*** End Patch"
            result = approved_tool_guard(
                tool_name="apply_patch", tool_input={"patch": patch}, project_root=root,
                scope={"paths": ["src/"], "commands": [], "external_effects": []},
            )
            self.assertEqual(result.decision, Decision.DENY)
            self.assertEqual(classify_tool("view_image", {"path": "image.png"}).decision, Decision.ALLOW)
            self.assertEqual(classify_tool("mcp__slack__send_message", {}).decision, Decision.NEEDS_HUMAN_JUDGMENT)
            self.assertEqual(
                approved_tool_guard(
                    tool_name="mcp__slack__send_message", tool_input={}, project_root=root,
                    scope={"paths": ["src/"], "commands": [], "external_effects": []},
                ).decision,
                Decision.NEEDS_HUMAN_JUDGMENT,
            )

class PublishedSchemaTests(unittest.TestCase):
    def test_json_schema_combinators_and_pass_receipts_match_runtime(self) -> None:
        def walk(value: object, location: str) -> None:
            if isinstance(value, dict):
                for keyword in ("allOf", "anyOf", "oneOf", "prefixItems"):
                    if keyword in value:
                        self.assertIsInstance(value[keyword], list, f"{location}/{keyword}")
                for key, child in value.items():
                    walk(child, f"{location}/{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, f"{location}/{index}")

        for path in sorted((ROOT / "spec").glob("*.schema.json")):
            walk(json.loads(path.read_text(encoding="utf-8")), path.name)

        receipt = json.loads((ROOT / "spec" / "reviewer-receipt.schema.json").read_text(encoding="utf-8"))
        branches = {item["title"]: item for item in receipt["oneOf"]}
        for title in ("Plan critic receipt", "Verifier receipt"):
            properties = branches[title]["properties"]
            self.assertEqual(properties["verdict"], {"const": "PASS"})
            for field in ("blocking_findings", "high_findings", "context_contamination"):
                self.assertEqual(properties[field]["maxItems"], 0)
        verifier = branches["Verifier receipt"]["properties"]
        self.assertEqual(verifier["scope_matches_approval"], {"const": True})
        self.assertEqual(verifier["approval_current"], {"const": True})

class StorageTests(unittest.TestCase):
    def test_event_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            log = EventLog(path)
            log.append({"operation": "one"})
            text = path.read_text(encoding="utf-8").replace('"one"', '"two"')
            path.write_text(text, encoding="utf-8", newline="\n")
            with self.assertRaises(IntegrityError):
                log.read_verified()

    def test_event_record_matches_published_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = EventLog(Path(directory) / "events.jsonl")
            log.append({"operation": "initialize"})
            record = log.read_verified()[0]
            schema = json.loads((ROOT / "spec" / "event.schema.json").read_text(encoding="utf-8"))
            self.assertTrue(set(schema["required"]).issubset(record))
            self.assertIn(record["payload"]["operation"], schema["$defs"]["event_payload"]["properties"]["operation"]["enum"])

    def test_persistent_lock_path_is_safely_reacquired(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock"
            path.write_text(json.dumps({"pid": 99999999, "created_at": time.time() - 100, "token": "old"}), encoding="utf-8")
            with FileLock(path, stale_after=1, timeout=1) as first:
                self.assertTrue(path.exists())
                self.assertTrue(first._held)
            self.assertTrue(path.exists())
            self.assertEqual(FileLock(path)._read()["token"], first.token)
            with FileLock(path, timeout=1) as second:
                self.assertTrue(second._held)
            self.assertEqual(FileLock(path)._read()["token"], second.token)

class StateAndApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "Project With Spaces Delta-Case"
        self.project.mkdir()
        (self.project / "base.txt").write_text("base", encoding="utf-8")
        self.store = RuntimeStore(self.project, "run-1", root=self.root / "state")
        self.state = self.store.initialize(session_id="session-1", task_profile="build")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def enter_implementation_loop(self) -> None:
        for phase in (
            Phase.TERRITORY_DISCOVERY,
            Phase.UNKNOWNS_AND_BLINDSPOTS,
            Phase.OPTIONS_REFERENCES_OR_PROTOTYPES,
            Phase.ACCEPTANCE_CRITERIA,
            Phase.IMPLEMENTATION_PLAN,
            Phase.INDEPENDENT_PLAN_CRITIQUE,
            Phase.AWAITING_HUMAN_PLAN_APPROVAL,
        ):
            self.store.transition(session_id="session-1", to_phase=phase)
        self.store.transition(
            session_id="session-1",
            to_phase=Phase.IMPLEMENTATION_LOOP,
            approval_valid=True,
        )

    def begin_act(self, index: int) -> None:
        self.store.begin_act(
            session_id="session-1",
            approval_bundle_hash="a" * 64,
            tool_name="Write",
            tool_input_hash=(format(index, "064x"))[-64:],
            project_fingerprint_before="b" * 64,
        )

    def test_state_snapshot_matches_published_required_fields(self) -> None:
        schema = json.loads((ROOT / "spec" / "state.schema.json").read_text(encoding="utf-8"))
        self.assertTrue(set(schema["required"]).issubset(self.state))
        self.assertEqual(self.state["schema_version"], schema["properties"]["schema_version"]["const"])
        self.assertIn(self.state["terminal_state"], schema["properties"]["terminal_state"]["enum"])

    def test_attempts_are_one_to_one_and_three_distinct_no_gain_failures_stop(self) -> None:
        self.enter_implementation_loop()
        common = {
            "session_id": "session-1",
            "approval_bundle_hash": "a" * 64,
            "step": "S1",
            "project_fingerprint": "b" * 64,
            "authority_valid_at_close": True,
            "authority_invalid_reasons": [],
            "scope_valid_at_close": True,
            "unapproved_paths": [],
            "failed": True,
            "evidence_gain": False,
        }
        with self.assertRaises(LifecycleError):
            self.store.record_attempt(
                **common, hypothesis="same", action="same", evidence_snapshot={"unchanged": True}
            )

        self.begin_act(1)
        self.store.record_attempt(
            **common, hypothesis="same", action="same", evidence_snapshot={"unchanged": True}
        )
        with self.assertRaises(LifecycleError):
            self.store.record_attempt(
                **common, hypothesis="same", action="same", evidence_snapshot={"unchanged": True}
            )

        self.begin_act(2)
        with self.assertRaises(LifecycleError):
            self.store.record_attempt(
                **common, hypothesis="same", action="same", evidence_snapshot={"unchanged": True}
            )
        self.store.record_attempt(
            **common,
            hypothesis="hypothesis-2",
            action="action-2",
            evidence_snapshot={"observation": 2},
        )
        self.begin_act(3)
        state = self.store.record_attempt(
            **common,
            hypothesis="hypothesis-3",
            action="action-3",
            evidence_snapshot={"observation": 3},
        )
        self.assertTrue(state["must_stop"])
        self.assertEqual(state["repeated_no_gain_failures"], 3)
        self.assertFalse(state["evidence"]["pending_attempt"]["active"])
        self.assertEqual(len({item["act_id"] for item in state["attempts"]}), 3)
        self.store.set_terminal(
            session_id="session-1",
            terminal_state=TerminalState.AWAITING_HUMAN_INPUT,
            reason="Three distinct attempts produced no evidence gain",
            evidence={"attempts": 3},
            resume_condition="Human supplies new evidence",
        )
        resumed = self.store.resume(session_id="session-1")
        self.assertFalse(resumed["must_stop"])
        self.assertEqual(resumed["repeated_no_gain_failures"], 0)
    def test_not_applicable_is_policy_bounded(self) -> None:
        self.store.transition(session_id="session-1", to_phase=Phase.TERRITORY_DISCOVERY)
        self.store.transition(session_id="session-1", to_phase=Phase.UNKNOWNS_AND_BLINDSPOTS)
        self.store.transition(session_id="session-1", to_phase=Phase.OPTIONS_REFERENCES_OR_PROTOTYPES)
        with self.assertRaises(LifecycleError):
            self.store.transition(
                session_id="session-1", to_phase=Phase.ACCEPTANCE_CRITERIA,
                outcome=PhaseStatus.NOT_APPLICABLE, reason="easy",
            )
        self.store.transition(
            session_id="session-1", to_phase=Phase.ACCEPTANCE_CRITERIA,
            outcome=PhaseStatus.NOT_APPLICABLE, reason="Only one low-risk textual correction is possible",
            not_applicable_code="single_mechanical_outcome",
            evidence={"only_viable_change": "one literal replacement", "risk_assessment": "no interface impact"},
        )

    def test_approval_tamper_and_stale_material(self) -> None:
        material = plan_material(plan=["one"], scope={"paths": ["."]}, acceptance=["pass"], critic=["ok"], base_fingerprint="base")
        observation = observe_human_event(
            host="claude", event_name="UserPromptSubmit",
            payload={"actor_type": "human", "prompt": approval_syntax("run-1", material["bundle_hash"]), "session_id": "session-1", "event_id": "event-1"},
        )
        authority = AuthorityStore(self.store.paths)
        authority.create(observation=observation, run_id="run-1", project=self.store.identity, material=material, scope={"paths": ["."]})
        valid, reasons, _ = authority.validate(run_id="run-1", session_id="session-1", project=self.store.identity, material=material)
        self.assertTrue(valid, reasons)
        stale = dict(material, plan_hash="0" * 64)
        valid, reasons, _ = authority.validate(run_id="run-1", session_id="session-1", project=self.store.identity, material=stale)
        self.assertFalse(valid)
        self.assertIn("plan_hash changed", reasons)
        document = json.loads(self.store.paths["approval"].read_text(encoding="utf-8"))
        document["receipt"]["scope"] = {"paths": ["outside"]}
        self.store.paths["approval"].write_text(json.dumps(document), encoding="utf-8")
        valid, reasons, _ = authority.validate(run_id="run-1", session_id="session-1", project=self.store.identity, material=material)
        self.assertFalse(valid)
        self.assertIn("approval signature is invalid", reasons)


if __name__ == "__main__":
    unittest.main()








