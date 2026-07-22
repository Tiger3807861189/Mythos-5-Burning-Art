from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[2] / "src" / "shared" / "runtime"
sys.path.insert(0, str(RUNTIME))

from mythos_runtime.canonical import compute_base_fingerprint
from mythos_runtime.hooks import REVIEWER_LAUNCH_PROMPT, _has_decision_packet, handle_hook
from mythos_runtime.lifecycle import Phase, TerminalState
from mythos_runtime.protocol import wire_result
from mythos_runtime.policy import Decision
from mythos_runtime.state import RuntimeStore, done_guard_failures


class ProtocolTests(unittest.TestCase):
    def test_pre_tool_use_is_host_valid_and_fail_closed(self) -> None:
        self.assertEqual(wire_result(Decision.ALLOW, "ok", host="codex", event="PreToolUse"), {})
        denied = wire_result(Decision.NEEDS_HUMAN_JUDGMENT, "unclear", host="claude", event="PreToolUse")
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_permission_allow_defers_to_native_host_policy(self) -> None:
        self.assertEqual(wire_result(Decision.ALLOW, "in scope", host="claude", event="PermissionRequest"), {})

    @staticmethod
    def decision_question(number: int, text: str = "Bounded implementation direction") -> str:
        return "\n".join([
            f"{number}. **{text}**",
            "   - Why this matters: The choice changes the implementation boundary.",
            "   - Evidence or uncertainty: The repository supports both directions.",
            "   - A. **Recommended safe direction** — It preserves the boundary with a known tradeoff.",
            "   - B. Alternative direction — It changes the boundary with a different tradeoff.",
            "   - C. Narrow direction — It reduces scope but leaves a known limitation.",
            "   - D. Stop or provide a constrained custom answer.",
            "   - If unanswered: No safe default; work remains blocked.",
        ])

    def test_exact_decision_packet_grammar_and_limits(self) -> None:
        self.assertTrue(_has_decision_packet(self.decision_question(1)))
        translated_labels = (
            self.decision_question(1)
            .replace("Why this matters", "Decision impact")
            .replace("Evidence or uncertainty", "Observed facts and gap")
            .replace("If unanswered", "If no response arrives")
        )
        self.assertTrue(_has_decision_packet(translated_labels))
        five = "\n\n".join(self.decision_question(index) for index in range(1, 6))
        self.assertTrue(_has_decision_packet(five))
        six = five + "\n\n" + self.decision_question(6)
        self.assertFalse(_has_decision_packet(six))
        gap = self.decision_question(1) + "\n\n" + self.decision_question(3)
        self.assertFalse(_has_decision_packet(gap))
        missing = self.decision_question(1).replace("   - D. Stop or provide a constrained custom answer.\n", "")
        self.assertFalse(_has_decision_packet(missing))
        unnumbered = self.decision_question(1) + "\nShould I also change the API?"
        self.assertFalse(_has_decision_packet(unnumbered))
        hidden_sixth = self.decision_question(1) + "\n\n6. **Sixth choice**\n   - A. **One** — one\n   - B. Two — two\n   - C. Three — three\n   - D. Four"
        self.assertFalse(_has_decision_packet(hidden_sixth))
        self.assertFalse(_has_decision_packet("Introductory prose\n" + self.decision_question(1)))
        self.assertFalse(_has_decision_packet(self.decision_question(1) + "\nTrailing prose"))
        self.assertFalse(_has_decision_packet(self.decision_question(1).replace("   - A.", "  - A.")))
        reordered = self.decision_question(1).replace(
            "   - A. **Recommended safe direction** — It preserves the boundary with a known tradeoff.\n   - B. Alternative direction — It changes the boundary with a different tradeoff.",
            "   - B. Alternative direction — It changes the boundary with a different tradeoff.\n   - A. **Recommended safe direction** — It preserves the boundary with a known tradeoff.",
        )
        self.assertFalse(_has_decision_packet(reordered))
        duplicate = self.decision_question(1).replace(
            "   - B. Alternative direction — It changes the boundary with a different tradeoff.",
            "   - A. **Duplicate direction** — Duplicate.\n   - B. Alternative direction — It changes the boundary with a different tradeoff.",
        )
        self.assertFalse(_has_decision_packet(duplicate))
        marked = self.decision_question(1) + "\n\nMYTHOS_WAITING_FOR_HUMAN_V1"
        self.assertTrue(_has_decision_packet(marked))
        self.assertFalse(_has_decision_packet(marked + "\nnot trailing"))


class HookFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "base.txt").write_text("base", encoding="utf-8")
        self.state_root = self.root / "state"
        self.prior_state_home = os.environ.get("MYTHOS5_STATE_HOME")
        os.environ["MYTHOS5_STATE_HOME"] = str(self.state_root)
        self.common = {"session_id": "session-1", "cwd": str(self.project), "transcript_path": str(self.root / "transcripts" / "session-1.jsonl")}
        start = handle_hook(host="codex", event="SessionStart", payload={**self.common, "source": "startup"})
        context = start["hookSpecificOutput"]["additionalContext"]
        self.run_id = re.search(r"Run ID: (m5-[a-f0-9]+)", context).group(1)
        handle_hook(
            host="codex",
            event="UserPromptSubmit",
            payload={**self.common, "turn_id": "turn-1", "prompt": "Implement a small feature"},
        )

    def tearDown(self) -> None:
        if self.prior_state_home is None:
            os.environ.pop("MYTHOS5_STATE_HOME", None)
        else:
            os.environ["MYTHOS5_STATE_HOME"] = self.prior_state_home
        self.temp.cleanup()

    def test_current_codex_exec_command_event_shape_for_discovery_and_approved_command(self) -> None:
        discovery = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={
                **self.common,
                "tool_name": "exec_command",
                "tool_input": {"cmd": "rg --files", "workdir": str(self.project)},
            },
        )
        self.assertEqual(discovery, {})

        packet = self.review_packet()
        command = "python -m unittest"
        tool_use_id = "codex-call-1"
        tool_input = {"cmd": command, "workdir": str(self.project)}
        packet["mutation_scope"]["commands"] = [command]
        _, approval_hash = self.approve(packet)
        approved = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={
                **self.common,
                "tool_use_id": tool_use_id,
                "tool_name": "exec_command",
                "tool_input": tool_input,
            },
        )
        self.assertEqual(approved, {})
        store = RuntimeStore(self.project, self.run_id, root=self.state_root)
        pending = store.load()["evidence"]["pending_attempt"]
        self.assertEqual(pending["tool_name"], "exec_command")
        self.assertEqual(pending["tool_use_id"], tool_use_id)

        mismatched = handle_hook(
            host="codex",
            event="PermissionRequest",
            payload={
                **self.common,
                "tool_use_id": tool_use_id,
                "tool_name": "exec_command",
                "tool_input": {**tool_input, "cmd": command + " --extra"},
            },
        )
        self.assertEqual(mismatched["hookSpecificOutput"]["decision"]["behavior"], "deny")

        wrong_id = handle_hook(
            host="codex",
            event="PermissionRequest",
            payload={
                **self.common,
                "tool_use_id": "codex-call-other",
                "tool_name": "exec_command",
                "tool_input": tool_input,
            },
        )
        self.assertEqual(wrong_id["hookSpecificOutput"]["decision"]["behavior"], "deny")

        permission = handle_hook(
            host="codex",
            event="PermissionRequest",
            payload={
                **self.common,
                "tool_use_id": tool_use_id,
                "tool_name": "exec_command",
                "tool_input": tool_input,
            },
        )
        self.assertEqual(permission, {})
        observed = store.load()["evidence"]["pending_attempt"]
        self.assertEqual(observed["act_id"], pending["act_id"])
        self.assertTrue(observed["permission_request_observed"])
        self.assertEqual(observed["permission_request_count"], 1)

        denied_attempt = {
            "schema_version": 1,
            "run_id": self.run_id,
            "approval_bundle_hash": approval_hash,
            "step": "P-1",
            "hypothesis": "The host will permit the exact approved diagnostic command",
            "action": "Requested native permission; the human denied it and the command did not run",
            "evidence_snapshot": "Native permission denial observed; project content remained unchanged",
            "outcome": "FAIL",
            "evidence_gain": True,
        }
        closed = self.stop_with(
            "MYTHOS_ATTEMPT_PACKET_V1_BEGIN",
            denied_attempt,
            "MYTHOS_ATTEMPT_PACKET_V1_END",
        )
        self.assertIn("recorded", closed["reason"])
        state = store.load()
        self.assertFalse(state["evidence"]["pending_attempt"]["active"])
        self.assertTrue(state["attempts"][-1]["failed"])
        self.assertEqual(state["attempts"][-1]["tool_use_id"], tool_use_id)
        self.assertTrue(state["attempts"][-1]["permission_request_observed"])
        self.assertEqual(state["attempts"][-1]["permission_request_count"], 1)

        orphan = handle_hook(
            host="codex",
            event="PermissionRequest",
            payload={
                **self.common,
                "tool_use_id": "codex-call-2",
                "tool_name": "exec_command",
                "tool_input": tool_input,
            },
        )
        self.assertEqual(orphan["hookSpecificOutput"]["decision"]["behavior"], "deny")
    def test_claude_permission_request_continues_the_same_pretool_act(self) -> None:
        _, approval_hash = self.approve()
        tool_use_id = "claude-call-1"
        tool_input = {"file_path": str(self.project / "foo.py")}
        pretool = handle_hook(
            host="claude",
            event="PreToolUse",
            payload={
                **self.common,
                "tool_use_id": tool_use_id,
                "tool_name": "Write",
                "tool_input": tool_input,
            },
        )
        self.assertEqual(pretool, {})
        store = RuntimeStore(self.project, self.run_id, root=self.state_root)
        act_id = store.load()["evidence"]["pending_attempt"]["act_id"]

        permission = handle_hook(
            host="claude",
            event="PermissionRequest",
            payload={
                **self.common,
                "tool_use_id": tool_use_id,
                "tool_name": "Write",
                "tool_input": tool_input,
            },
        )
        self.assertEqual(permission, {})
        observed = store.load()["evidence"]["pending_attempt"]
        self.assertEqual(observed["act_id"], act_id)
        self.assertTrue(observed["permission_request_observed"])

        closed = self.stop_with(
            "MYTHOS_ATTEMPT_PACKET_V1_BEGIN",
            {
                "schema_version": 1,
                "run_id": self.run_id,
                "approval_bundle_hash": approval_hash,
                "step": "P-1",
                "hypothesis": "The host will authorize the approved file write",
                "action": "Requested native permission; the human denied it and no file was written",
                "evidence_snapshot": "Native permission denial observed; foo.py remains absent",
                "outcome": "FAIL",
                "evidence_gain": True,
            },
            "MYTHOS_ATTEMPT_PACKET_V1_END",
        )
        self.assertIn("recorded", closed["reason"])
        final_state = store.load()
        self.assertFalse(final_state["evidence"]["pending_attempt"]["active"])
        self.assertEqual(final_state["attempts"][-1]["tool_use_id"], tool_use_id)
        self.assertTrue(final_state["attempts"][-1]["permission_request_observed"])
    def review_packet(self) -> dict:
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "task_profile": "build",
            "goal": "Create foo.py",
            "intake": {
                "outcome": "foo.py exists",
                "scope": "one file",
                "constraints": ["stdlib"],
                "non_goals": ["deployment"],
                "authorization": "planning only before approval",
            },
            "territory_discovery": {
                "repository_map": ["base.txt"],
                "instructions": ["none"],
                "conventions": ["stdlib"],
                "baseline": "clean",
            },
            "unknowns": {
                "known_knowns": ["one file"],
                "known_unknowns": ["none"],
                "unknown_knowns": ["none"],
                "unknown_unknowns": ["scanned"],
                "blindspot_pass": ["scope"],
            },
            "options": {"status": "PASS", "disposition": "Create the smallest module"},
            "acceptance_criteria": [
                {"id": "AC-1", "pass_condition": "foo.py exists", "verification": "read"}
            ],
            "plan": [
                {
                    "id": "P-1",
                    "surfaces": ["foo.py"],
                    "action": "create",
                    "verification": "read",
                    "rollback": "delete foo.py",
                }
            ],
            "mutation_scope": {"paths": ["foo.py"], "commands": [], "external_effects": []},
        }

    def stop_with(self, begin: str, value: dict, end: str) -> dict:
        message = f"{begin}\n```json\n{json.dumps(value)}\n```\n{end}"
        return handle_hook(host="codex", event="Stop", payload={**self.common, "last_assistant_message": message})

    def seal_review(self, packet: dict | None = None) -> tuple[dict, str]:
        packet = packet or self.review_packet()
        result = self.stop_with("MYTHOS_REVIEW_PACKET_V1_BEGIN", packet, "MYTHOS_REVIEW_PACKET_V1_END")
        packet_hash = re.search(r"([a-f0-9]{64})", result["reason"]).group(1)
        self.assertEqual(result["decision"], "block")
        return packet, packet_hash

    def agent_transcript(self, agent_id: str) -> str:
        main = Path(self.common["transcript_path"])
        return str(main.parent / main.stem / "subagents" / f"agent-{agent_id}.jsonl")

    def record_reviewer_launch(self, role: str, *, host: str = "codex") -> dict:
        if host == "claude":
            tool_name = "Agent"
            tool_input = {"subagent_type": role, "prompt": REVIEWER_LAUNCH_PROMPT}
        else:
            tool_name = "spawn_agent"
            tool_input = {
                "task_name": role.replace("-", "_"),
                "message": REVIEWER_LAUNCH_PROMPT,
                "fork_turns": "none",
            }
        return handle_hook(
            host=host,
            event="PreToolUse",
            payload={**self.common, "tool_name": tool_name, "tool_input": tool_input},
        )

    def pass_critic(
        self,
        packet_hash: str,
        *,
        agent_id: str = "critic-1",
        receipt_override: dict | None = None,
        extra_verdict: str | None = None,
    ) -> dict:
        launch = self.record_reviewer_launch("mythos-plan-critic")
        self.assertEqual(launch, {})
        started = handle_hook(
            host="codex",
            event="SubagentStart",
            payload={**self.common, "agent_id": agent_id, "agent_type": "mythos-plan-critic"},
        )
        context = started["hookSpecificOutput"]["additionalContext"]
        self.assertIn(packet_hash, context)
        self.assertIn('"goal":', context)
        receipt = receipt_override or {
            "schema_version": 1,
            "packet_hash": packet_hash,
            "verdict": "PASS",
            "reviewed_sections": ["task_profile", "replan_provenance", "original_request", "context_manifest", "goal", "intake", "territory_discovery", "unknowns", "options", "acceptance_criteria", "plan", "mutation_scope"],
            "blocking_findings": [],
            "high_findings": [],
            "context_contamination": [],
        }
        lines = ["Verdict: PASS"]
        if extra_verdict:
            lines.append(f"Verdict: {extra_verdict}")
        lines.extend([
            "MYTHOS_CRITIC_RECEIPT_V1_BEGIN",
            json.dumps(receipt),
            "MYTHOS_CRITIC_RECEIPT_V1_END",
        ])
        return handle_hook(
            host="codex",
            event="SubagentStop",
            payload={
                **self.common,
                "agent_id": agent_id,
                "agent_type": "mythos-plan-critic",
                "agent_transcript_path": self.agent_transcript(agent_id),
                "last_assistant_message": chr(10).join(lines),
            },
        )

    def approve(self, packet: dict | None = None) -> tuple[str, str]:
        packet, packet_hash = self.seal_review(packet)
        self.pass_critic(packet_hash)
        bundle = {
            **packet,
            "review_packet_hash": packet_hash,
            "critic": {"adjudication": [{"finding": "none", "disposition": "ACCEPT", "evidence": "PASS"}]},
        }
        stopped = self.stop_with(
            "MYTHOS_APPROVAL_BUNDLE_V1_BEGIN", bundle, "MYTHOS_APPROVAL_BUNDLE_V1_END"
        )
        approval = re.search(r"APPROVE MYTHOS RUN .* BUNDLE [a-f0-9]{64}", stopped["systemMessage"]).group(0)
        approved = handle_hook(
            host="codex",
            event="UserPromptSubmit",
            payload={**self.common, "turn_id": "turn-2", "prompt": approval},
        )
        self.assertIn("hookSpecificOutput", approved)
        return approval, approval.rsplit(" ", 1)[-1]

    def authorize_step(self, step: dict | None = None) -> None:
        state = RuntimeStore(self.project, self.run_id, root=self.state_root).load()
        raw = state["evidence"]["approval_material"]
        step = step or raw["plan"][0]
        if raw["scope"]["commands"]:
            tool_name = "exec_command"
            tool_input = {"cmd": raw["scope"]["commands"][0], "workdir": str(self.project)}
        else:
            surface = step["surfaces"][0]
            tool_name = "Write"
            tool_input = {"file_path": str(self.project / surface)}
        result = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={**self.common, "tool_name": tool_name, "tool_input": tool_input},
        )
        self.assertEqual(result, {})

    def verification_packet(self, approval_hash: str) -> dict:
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "approval_bundle_hash": approval_hash,
            "implementation_notes": {"summary": "Created foo.py", "changed_surfaces": ["foo.py"]},
            "increment_evidence": [{"step": "P-1", "observation": "file exists", "result": "PASS"}],
            "acceptance_evidence": [{"criterion": "AC-1", "evidence": "read foo.py", "result": "PASS"}],
            "reconciliation": {
                "deviations": [
                    {"subject_type": "PLAN_STEP", "subject_id": "P-1", "classification": "MATCH", "evidence": "approved step completed"},
                    {"subject_type": "PATH", "subject_id": "foo.py", "classification": "MATCH", "evidence": "hook-observed file change"}
                ]
            },
        }

    def record_passing_attempts(self, approval_hash: str) -> None:
        store = RuntimeStore(self.project, self.run_id, root=self.state_root)
        state = store.load()
        plan = state["evidence"]["approval_material"]["plan"]
        passed_steps = {
            item["step"] for item in state["attempts"]
            if item["approval_bundle_hash"] == approval_hash and not item["failed"] and item["evidence_gain"]
        }
        for step in plan:
            if step["id"] in passed_steps:
                continue
            state = store.load()
            if state.get("evidence", {}).get("pending_attempt", {}).get("active") is not True:
                self.authorize_step(step)
                state = store.load()
            packet = {
                "schema_version": 1,
                "run_id": self.run_id,
                "approval_bundle_hash": approval_hash,
                "step": step["id"],
                "hypothesis": "The bounded approved action produced its expected observation",
                "action": step["action"],
                "evidence_snapshot": f"Current project content and direct observation recorded at attempt {len(state['attempts']) + 1}",
                "outcome": "PASS",
                "evidence_gain": True,
            }
            result = self.stop_with(
                "MYTHOS_ATTEMPT_PACKET_V1_BEGIN", packet, "MYTHOS_ATTEMPT_PACKET_V1_END"
            )
            self.assertEqual(result["decision"], "block")
            self.assertIn("recorded", result["reason"])
    def seal_verification(self, packet: dict) -> str:
        state = RuntimeStore(self.project, self.run_id, root=self.state_root).load()
        if state["task_profile"] != "plan_only":
            self.record_passing_attempts(packet["approval_bundle_hash"])
        result = self.stop_with(
            "MYTHOS_VERIFICATION_PACKET_V1_BEGIN", packet, "MYTHOS_VERIFICATION_PACKET_V1_END"
        )
        self.assertEqual(result["decision"], "block")
        return re.search(r"([a-f0-9]{64})", result["reason"]).group(1)

    def pass_verifier(
        self,
        packet_hash: str,
        *,
        agent_id: str = "verifier-1",
        receipt_override: dict | None = None,
        extra_verdict: str | None = None,
    ) -> dict:
        launch = self.record_reviewer_launch("mythos-verifier")
        self.assertEqual(launch, {})
        started = handle_hook(
            host="codex",
            event="SubagentStart",
            payload={**self.common, "agent_id": agent_id, "agent_type": "mythos-verifier"},
        )
        context = started["hookSpecificOutput"]["additionalContext"]
        self.assertIn(packet_hash, context)
        self.assertIn(compute_base_fingerprint(self.project), context)
        self.assertIn('"acceptance_evidence"', context)
        receipt = receipt_override or {
            "schema_version": 1,
            "packet_hash": packet_hash,
            "verdict": "PASS",
            "criteria": [{"criterion": "AC-1", "result": "PASS", "evidence": "read foo.py"}],
            "scope_matches_approval": True,
            "approval_current": True,
            "blocking_findings": [],
            "high_findings": [],
            "context_contamination": [],
        }
        lines = ["Verdict: PASS"]
        if extra_verdict:
            lines.append(f"Verdict: {extra_verdict}")
        lines.extend([
            "MYTHOS_VERIFIER_RECEIPT_V1_BEGIN",
            json.dumps(receipt),
            "MYTHOS_VERIFIER_RECEIPT_V1_END",
        ])
        return handle_hook(
            host="codex",
            event="SubagentStop",
            payload={
                **self.common,
                "agent_id": agent_id,
                "agent_type": "mythos-verifier",
                "agent_transcript_path": self.agent_transcript(agent_id),
                "last_assistant_message": chr(10).join(lines),
            },
        )

    def completion(self, packet: dict, packet_hash: str) -> dict:
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "verification_packet_hash": packet_hash,
            "implementation_notes": packet["implementation_notes"],
            "increment_evidence": packet["increment_evidence"],
            "acceptance_evidence": packet["acceptance_evidence"],
            "reconciliation": packet["reconciliation"],
            "explanation": {
                "change_explanation": "Created one module",
                "risks": ["none"],
                "rollback": "delete foo.py",
                "comprehension_evidence": "low-impact waiver",
            },
        }

    def test_full_bound_plan_build_verify_done(self) -> None:
        approval, approval_hash = self.approve()
        self.authorize_step()
        outside = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={**self.common, "tool_name": "Write", "tool_input": {"file_path": str(self.root / "outside.py")}},
        )
        self.assertEqual(outside["hookSpecificOutput"]["permissionDecision"], "deny")
        (self.project / "foo.py").write_text("VALUE = 1\n", encoding="utf-8")

        packet = self.verification_packet(approval_hash)
        verification_hash = self.seal_verification(packet)
        self.pass_verifier(verification_hash)
        result = self.stop_with(
            "MYTHOS_COMPLETION_BUNDLE_V1_BEGIN",
            self.completion(packet, verification_hash),
            "MYTHOS_COMPLETION_BUNDLE_V1_END",
        )
        self.assertEqual(result, {})
        store = RuntimeStore(self.project, self.run_id, root=self.state_root)
        state = store.load()
        self.assertEqual(state["phase"], Phase.DONE.value)
        self.assertEqual(done_guard_failures(state), [])

        handle_hook(
            host="codex",
            event="UserPromptSubmit",
            payload={**self.common, "turn_id": "turn-after-done", "prompt": approval},
        )
        denied = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={**self.common, "tool_name": "Write", "tool_input": {"file_path": str(self.project / "foo.py")}},
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_verification_freeze_requires_replan_after_post_seal_change(self) -> None:
        _, approval_hash = self.approve()
        self.authorize_step()
        (self.project / "foo.py").write_text("VALUE = 1\n", encoding="utf-8")
        packet = self.verification_packet(approval_hash)
        verification_hash = self.seal_verification(packet)
        self.pass_verifier(verification_hash)

        (self.project / "foo.py").write_text("VALUE = 2\n", encoding="utf-8")
        stale = self.stop_with(
            "MYTHOS_COMPLETION_BUNDLE_V1_BEGIN",
            self.completion(packet, verification_hash),
            "MYTHOS_COMPLETION_BUNDLE_V1_END",
        )
        self.assertEqual(stale["decision"], "block")
        self.assertIn("final_fingerprint does not match the current project", stale["reason"])
        denied = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={**self.common, "tool_name": "Write", "tool_input": {"file_path": str(self.project / "foo.py")}},
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("verification snapshot is frozen", denied["hookSpecificOutput"]["permissionDecisionReason"])
    def test_critic_is_bound_to_exact_hook_sealed_packet(self) -> None:
        packet, packet_hash = self.seal_review()
        self.pass_critic(packet_hash)
        changed = json.loads(json.dumps(packet))
        changed["plan"][0]["action"] = "create and silently expand"
        bundle = {
            **changed,
            "review_packet_hash": packet_hash,
            "critic": {"adjudication": [{"finding": "none", "disposition": "ACCEPT", "evidence": "PASS"}]},
        }
        result = self.stop_with(
            "MYTHOS_APPROVAL_BUNDLE_V1_BEGIN", bundle, "MYTHOS_APPROVAL_BUNDLE_V1_END"
        )
        self.assertEqual(result["decision"], "block")
        self.assertIn("planning fields differ", result["reason"])

        packet, packet_hash = self.seal_review(packet)
        wrong_receipt = {
            "schema_version": 1,
            "packet_hash": "0" * 64,
            "verdict": "PASS",
            "reviewed_sections": ["plan"],
            "blocking_findings": [],
            "high_findings": [],
            "context_contamination": [],
        }
        self.pass_critic(packet_hash, agent_id="critic-wrong", receipt_override=wrong_receipt)
        bundle = {
            **packet,
            "review_packet_hash": packet_hash,
            "critic": {"adjudication": [{"finding": "none", "disposition": "ACCEPT", "evidence": "PASS"}]},
        }
        result = self.stop_with(
            "MYTHOS_APPROVAL_BUNDLE_V1_BEGIN", bundle, "MYTHOS_APPROVAL_BUNDLE_V1_END"
        )
        self.assertIn("no accepted terminal PASS", result["reason"])
    def test_verification_rejects_missing_acceptance_and_out_of_scope(self) -> None:
        _, approval_hash = self.approve()
        self.authorize_step()
        (self.project / "foo.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.record_passing_attempts(approval_hash)
        packet = self.verification_packet(approval_hash)
        packet["acceptance_evidence"] = [{"criterion": "AC-1", "evidence": "not run", "result": "FAIL"}]
        result = self.stop_with(
            "MYTHOS_VERIFICATION_PACKET_V1_BEGIN", packet, "MYTHOS_VERIFICATION_PACKET_V1_END"
        )
        self.assertIn("did not pass", result["reason"])

        self.authorize_step()
        (self.project / "bar.py").write_text("OUTSIDE = 1\n", encoding="utf-8")
        attempt = {
            "schema_version": 1,
            "run_id": self.run_id,
            "approval_bundle_hash": approval_hash,
            "step": "P-1",
            "hypothesis": "The approved tool may have affected an unexpected path",
            "action": "observe the complete command-sensitive project surface",
            "evidence_snapshot": "bar.py appeared outside the approved path",
            "outcome": "FAIL",
            "evidence_gain": True,
        }
        result = self.stop_with(
            "MYTHOS_ATTEMPT_PACKET_V1_BEGIN", attempt, "MYTHOS_ATTEMPT_PACKET_V1_END"
        )
        self.assertIn("exceeded approved paths", result["reason"])
        state = RuntimeStore(self.project, self.run_id, root=self.state_root).load()
        self.assertEqual(state["phase"], Phase.UNKNOWNS_AND_BLINDSPOTS.value)
        self.assertFalse(state["attempts"][-1]["scope_valid_at_close"])
        self.assertEqual(state["attempts"][-1]["unapproved_paths"], ["bar.py"])
    def test_each_substantive_command_requires_its_own_attempt_packet(self) -> None:
        packet = self.review_packet()
        packet["mutation_scope"]["commands"] = ["python -B diagnose.py"]
        _, approval_hash = self.approve(packet)
        self.authorize_step()

        second = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={
                **self.common,
                "tool_name": "shell_command",
                "tool_input": {"command": "python -B diagnose.py", "workdir": str(self.project)},
            },
        )
        self.assertEqual(second["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("exact MYTHOS_ATTEMPT_PACKET_V1", second["hookSpecificOutput"]["permissionDecisionReason"])

        self.record_passing_attempts(approval_hash)
        third = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={
                **self.common,
                "tool_name": "shell_command",
                "tool_input": {"command": "python -B diagnose.py", "workdir": str(self.project)},
            },
        )
        self.assertEqual(third, {})
        state = RuntimeStore(self.project, self.run_id, root=self.state_root).load()
        self.assertTrue(state["evidence"]["pending_attempt"]["active"])
        self.assertRegex(state["evidence"]["pending_attempt"]["act_id"], r"^[a-f0-9]{32}$")

        replan = self.review_packet()
        replan["replan_from"] = Phase.UNKNOWNS_AND_BLINDSPOTS.value
        blocked_replan = self.stop_with(
            "MYTHOS_REVIEW_PACKET_V1_BEGIN", replan, "MYTHOS_REVIEW_PACKET_V1_END"
        )
        self.assertEqual(blocked_replan["decision"], "block")
        self.assertIn("pending substantive act", blocked_replan["reason"])

        terminal = self.stop_with(
            "MYTHOS_TERMINAL_PACKET_V1_BEGIN",
            {
                "schema_version": 1,
                "run_id": self.run_id,
                "terminal_state": "BLOCKED",
                "current_phase": Phase.IMPLEMENTATION_LOOP.value,
                "reason": "A concrete dependency is unavailable",
                "evidence": {"dependency": "missing"},
                "resume_condition": "The dependency becomes available",
            },
            "MYTHOS_TERMINAL_PACKET_V1_END",
        )
        self.assertEqual(terminal["decision"], "block")
        self.assertIn("Close the pending substantive act", terminal["reason"])

        waiting = handle_hook(
            host="codex",
            event="Stop",
            payload={
                **self.common,
                "last_assistant_message": ProtocolTests.decision_question(1) + "\n\nMYTHOS_WAITING_FOR_HUMAN_V1",
            },
        )
        self.assertEqual(waiting["decision"], "block")
        self.assertIn("Close the pending substantive act", waiting["reason"])
    def test_exact_command_monitors_generated_roots_and_rejects_unapproved_delta(self) -> None:
        packet = self.review_packet()
        packet["mutation_scope"]["commands"] = ["python -B diagnose.py"]
        _, approval_hash = self.approve(packet)
        self.authorize_step()
        generated = self.project / "node_modules"
        generated.mkdir()
        (generated / "unexpected.txt").write_text("unexpected", encoding="utf-8")
        result = self.stop_with(
            "MYTHOS_ATTEMPT_PACKET_V1_BEGIN",
            {
                "schema_version": 1,
                "run_id": self.run_id,
                "approval_bundle_hash": approval_hash,
                "step": "P-1",
                "hypothesis": "The exact command may emit files under a generated root",
                "action": "Inspect the complete command-sensitive project surface",
                "evidence_snapshot": "node_modules/unexpected.txt appeared",
                "outcome": "FAIL",
                "evidence_gain": True,
            },
            "MYTHOS_ATTEMPT_PACKET_V1_END",
        )
        self.assertEqual(result["decision"], "block")
        self.assertIn("exceeded approved paths", result["reason"])
        state = RuntimeStore(self.project, self.run_id, root=self.state_root).load()
        self.assertEqual(state["phase"], Phase.UNKNOWNS_AND_BLINDSPOTS.value)
        self.assertFalse(state["attempts"][-1]["scope_valid_at_close"])
        self.assertEqual(state["attempts"][-1]["unapproved_paths"], ["node_modules/unexpected.txt"])

        replan = self.review_packet()
        replan["replan_from"] = Phase.UNKNOWNS_AND_BLINDSPOTS.value
        laundering = self.stop_with(
            "MYTHOS_REVIEW_PACKET_V1_BEGIN", replan, "MYTHOS_REVIEW_PACKET_V1_END"
        )
        self.assertIn("cannot become a reapproval baseline", laundering["reason"])

        (generated / "unexpected.txt").unlink()
        _, new_packet_hash = self.seal_review(replan)
        self.assertRegex(new_packet_hash, r"^[a-f0-9]{64}$")
    def test_pending_act_can_be_closed_for_audit_after_human_invalidation(self) -> None:
        _, approval_hash = self.approve()
        self.authorize_step()
        changed = handle_hook(
            host="codex",
            event="UserPromptSubmit",
            payload={**self.common, "turn_id": "mid-act-change", "prompt": "Change the requested behavior"},
        )
        self.assertIn("new human approval", changed["hookSpecificOutput"]["additionalContext"])
        attempt = {
            "schema_version": 1,
            "run_id": self.run_id,
            "approval_bundle_hash": approval_hash,
            "step": "P-1",
            "hypothesis": "The already authorized act must remain auditable",
            "action": "Close the in-flight act without authorizing further work",
            "evidence_snapshot": "Approval was invalidated after the act began",
            "outcome": "FAIL",
            "evidence_gain": True,
        }
        closed = self.stop_with(
            "MYTHOS_ATTEMPT_PACKET_V1_BEGIN", attempt, "MYTHOS_ATTEMPT_PACKET_V1_END"
        )
        self.assertIn("recorded", closed["reason"])
        state = RuntimeStore(self.project, self.run_id, root=self.state_root).load()
        self.assertFalse(state["evidence"]["pending_attempt"]["active"])
        self.assertFalse(state["attempts"][-1]["authority_valid_at_close"])
        denied = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={**self.common, "tool_name": "Write", "tool_input": {"file_path": str(self.project / "foo.py")}},
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
    def test_new_human_instruction_invalidates_active_approval(self) -> None:
        self.approve()
        changed = handle_hook(
            host="codex",
            event="UserPromptSubmit",
            payload={**self.common, "turn_id": "turn-3", "prompt": "Also add an unrelated bar.py file"},
        )
        self.assertIn("new human approval", changed["hookSpecificOutput"]["additionalContext"])
        denied = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={**self.common, "tool_name": "Write", "tool_input": {"file_path": str(self.project / "foo.py")}},
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_read_only_exemption_is_not_sticky(self) -> None:
        other = {"session_id": "session-read", "cwd": str(self.project)}
        handle_hook(host="codex", event="SessionStart", payload={**other, "source": "startup"})
        handle_hook(
            host="codex",
            event="UserPromptSubmit",
            payload={**other, "turn_id": "r1", "prompt": "Explain what this repository is"},
        )
        stopped = handle_hook(
            host="codex", event="Stop", payload={**other, "last_assistant_message": "It is a small repository."}
        )
        self.assertEqual(stopped, {})
        handle_hook(
            host="codex",
            event="UserPromptSubmit",
            payload={**other, "turn_id": "r2", "prompt": "Implement a new file now"},
        )
        blocked = handle_hook(
            host="codex", event="Stop", payload={**other, "last_assistant_message": "Done"}
        )
        self.assertEqual(blocked["decision"], "block")
        denied = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={**other, "tool_name": "Write", "tool_input": {"file_path": str(self.project / "new.py")}},
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

    def approval_bundle(self, packet: dict, packet_hash: str) -> dict:
        return {
            **packet,
            "review_packet_hash": packet_hash,
            "critic": {"adjudication": [{"finding": "none", "disposition": "ACCEPT", "evidence": "PASS"}]},
        }

    def test_contradictory_or_blocking_critic_receipt_cannot_approve(self) -> None:
        packet, packet_hash = self.seal_review()
        rejected = self.pass_critic(packet_hash, extra_verdict="REVISE")
        self.assertEqual(rejected["decision"], "block")
        overwrite = handle_hook(
            host="codex",
            event="SubagentStart",
            payload={**self.common, "agent_id": "critic-overwrite", "agent_type": "mythos-plan-critic", "fork_turns": "none"},
        )
        self.assertIn("no active hook-sealed plan critic packet", overwrite["hookSpecificOutput"]["additionalContext"])
        result = self.stop_with(
            "MYTHOS_APPROVAL_BUNDLE_V1_BEGIN",
            self.approval_bundle(packet, packet_hash),
            "MYTHOS_APPROVAL_BUNDLE_V1_END",
        )
        self.assertIn("no accepted terminal PASS", result["reason"])

        packet, packet_hash = self.seal_review(packet)
        receipt = {
            "schema_version": 1,
            "packet_hash": packet_hash,
            "verdict": "PASS",
            "reviewed_sections": ["task_profile", "replan_provenance", "original_request", "context_manifest", "goal", "intake", "territory_discovery", "unknowns", "options", "acceptance_criteria", "plan", "mutation_scope"],
            "blocking_findings": ["scope is unsafe"],
            "high_findings": [],
            "context_contamination": [],
        }
        rejected = self.pass_critic(packet_hash, agent_id="critic-blocker", receipt_override=receipt)
        self.assertEqual(rejected["decision"], "block")
        result = self.stop_with(
            "MYTHOS_APPROVAL_BUNDLE_V1_BEGIN",
            self.approval_bundle(packet, packet_hash),
            "MYTHOS_APPROVAL_BUNDLE_V1_END",
        )
        self.assertIn("no accepted terminal PASS", result["reason"])
    def test_verification_requires_passing_increments_resolved_deviations_and_clean_receipt(self) -> None:
        _, approval_hash = self.approve()
        self.authorize_step()
        (self.project / "foo.py").write_text("VALUE = 1", encoding="utf-8")
        self.record_passing_attempts(approval_hash)

        failed = self.verification_packet(approval_hash)
        failed["increment_evidence"][0]["result"] = "FAIL"
        result = self.stop_with(
            "MYTHOS_VERIFICATION_PACKET_V1_BEGIN", failed, "MYTHOS_VERIFICATION_PACKET_V1_END"
        )
        self.assertIn("increment did not pass", result["reason"])

        unresolved = self.verification_packet(approval_hash)
        unresolved["reconciliation"]["deviations"][0]["classification"] = "UNRESOLVED"
        result = self.stop_with(
            "MYTHOS_VERIFICATION_PACKET_V1_BEGIN", unresolved, "MYTHOS_VERIFICATION_PACKET_V1_END"
        )
        self.assertIn("unresolved or unsupported", result["reason"])

        packet = self.verification_packet(approval_hash)
        packet_hash = self.seal_verification(packet)
        receipt = {
            "schema_version": 1,
            "packet_hash": packet_hash,
            "verdict": "PASS",
            "criteria": [{"criterion": "AC-1", "result": "PASS", "evidence": "read"}],
            "scope_matches_approval": True,
            "approval_current": True,
            "blocking_findings": [],
            "high_findings": ["race not tested"],
            "context_contamination": [],
        }
        rejected = self.pass_verifier(packet_hash, receipt_override=receipt)
        self.assertEqual(rejected["decision"], "block")
        self.assertIn("high_findings", rejected["reason"])
        state = RuntimeStore(self.project, self.run_id, root=self.state_root).load()
        self.assertEqual(state["phase"], Phase.UNKNOWNS_AND_BLINDSPOTS.value)
        result = self.stop_with(
            "MYTHOS_COMPLETION_BUNDLE_V1_BEGIN",
            self.completion(packet, packet_hash),
            "MYTHOS_COMPLETION_BUNDLE_V1_END",
        )
        self.assertIn("Independent verification rejected", result["systemMessage"])

    def test_verifier_rejection_is_terminal_for_packet_and_requires_new_approval(self) -> None:
        _, approval_hash = self.approve()
        self.authorize_step()
        (self.project / "foo.py").write_text("VALUE = 1\n", encoding="utf-8")
        packet = self.verification_packet(approval_hash)
        packet_hash = self.seal_verification(packet)
        receipt = {
            "schema_version": 1,
            "packet_hash": packet_hash,
            "verdict": "PASS",
            "criteria": [{"criterion": "AC-1", "result": "PASS", "evidence": "read"}],
            "scope_matches_approval": True,
            "approval_current": True,
            "blocking_findings": [],
            "high_findings": ["A high-severity risk remains"],
            "context_contamination": [],
        }
        rejected = self.pass_verifier(packet_hash, receipt_override=receipt)
        self.assertEqual(rejected["decision"], "block")

        state = RuntimeStore(self.project, self.run_id, root=self.state_root).load()
        self.assertEqual(state["phase"], Phase.UNKNOWNS_AND_BLINDSPOTS.value)
        self.assertEqual(state["terminal_state"], TerminalState.VERIFICATION_FAILED.value)
        self.assertFalse(state["evidence"]["pending_verification_packet"]["active"])
        self.assertEqual(state["evidence"]["pending_verification_packet"]["review_result"], "REJECTED")

        overwrite = handle_hook(
            host="codex",
            event="SubagentStart",
            payload={**self.common, "agent_id": "verifier-overwrite", "agent_type": "mythos-verifier", "fork_turns": "none"},
        )
        self.assertIn("no active hook-sealed verifier packet", overwrite["hookSpecificOutput"]["additionalContext"])
        completion = self.stop_with(
            "MYTHOS_COMPLETION_BUNDLE_V1_BEGIN",
            self.completion(packet, packet_hash),
            "MYTHOS_COMPLETION_BUNDLE_V1_END",
        )
        self.assertIn("Independent verification rejected", completion["systemMessage"])

        resumed = handle_hook(
            host="codex",
            event="UserPromptSubmit",
            payload={
                **self.common,
                "turn_id": "resume-after-verification-failure",
                "prompt": f"RESUME MYTHOS RUN {self.run_id}: acknowledge verifier evidence and replan",
            },
        )
        self.assertIn("hookSpecificOutput", resumed)

        replan = self.review_packet()
        replan["replan_from"] = Phase.UNKNOWNS_AND_BLINDSPOTS.value
        replan, review_hash = self.seal_review(replan)
        self.pass_critic(review_hash, agent_id="critic-after-verifier-rejection")
        approval_request = self.stop_with(
            "MYTHOS_APPROVAL_BUNDLE_V1_BEGIN",
            self.approval_bundle(replan, review_hash),
            "MYTHOS_APPROVAL_BUNDLE_V1_END",
        )
        self.assertRegex(
            approval_request["systemMessage"],
            r"APPROVE MYTHOS RUN .* BUNDLE [a-f0-9]{64}",
        )
    def test_plan_wait_is_explicit_terminal_and_feedback_requires_new_review(self) -> None:
        packet, packet_hash = self.seal_review()
        self.pass_critic(packet_hash)
        waiting = self.stop_with(
            "MYTHOS_APPROVAL_BUNDLE_V1_BEGIN",
            self.approval_bundle(packet, packet_hash),
            "MYTHOS_APPROVAL_BUNDLE_V1_END",
        )
        approval = re.search(r"APPROVE MYTHOS RUN .* BUNDLE [a-f0-9]{64}", waiting["systemMessage"]).group(0)
        state = RuntimeStore(self.project, self.run_id, root=self.state_root).load()
        self.assertEqual(state["phase"], Phase.AWAITING_HUMAN_PLAN_APPROVAL.value)
        self.assertEqual(state["terminal_state"], TerminalState.AWAITING_HUMAN_PLAN_APPROVAL.value)

        feedback = handle_hook(
            host="codex",
            event="UserPromptSubmit",
            payload={**self.common, "turn_id": "plan-feedback", "prompt": "Use a different public name."},
        )
        self.assertIn("Re-enter phase 3", feedback["hookSpecificOutput"]["additionalContext"])
        stale = handle_hook(
            host="codex",
            event="UserPromptSubmit",
            payload={**self.common, "turn_id": "stale-approval", "prompt": approval},
        )
        self.assertEqual(stale["decision"], "block")
    def test_plan_wait_is_explicit_terminal_and_feedback_requires_new_review(self) -> None:
        packet, packet_hash = self.seal_review()
        self.pass_critic(packet_hash)
        waiting = self.stop_with(
            "MYTHOS_APPROVAL_BUNDLE_V1_BEGIN",
            self.approval_bundle(packet, packet_hash),
            "MYTHOS_APPROVAL_BUNDLE_V1_END",
        )
        approval = re.search(r"APPROVE MYTHOS RUN .* BUNDLE [a-f0-9]{64}", waiting["systemMessage"]).group(0)
        state = RuntimeStore(self.project, self.run_id, root=self.state_root).load()
        self.assertEqual(state["phase"], Phase.AWAITING_HUMAN_PLAN_APPROVAL.value)
        self.assertEqual(state["terminal_state"], TerminalState.AWAITING_HUMAN_PLAN_APPROVAL.value)

        feedback = handle_hook(
            host="codex",
            event="UserPromptSubmit",
            payload={**self.common, "turn_id": "plan-feedback", "prompt": "Use a different public name."},
        )
        self.assertIn("Re-enter phase 3", feedback["hookSpecificOutput"]["additionalContext"])
        stale = handle_hook(
            host="codex",
            event="UserPromptSubmit",
            payload={**self.common, "turn_id": "stale-approval", "prompt": approval},
        )
        self.assertEqual(stale["decision"], "block")
    def test_compound_explanation_mutation_prompt_invalidates_approval(self) -> None:
        self.approve()
        changed = handle_hook(
            host="codex",
            event="UserPromptSubmit",
            payload={
                **self.common,
                "turn_id": "compound",
                "prompt": "Explain the current file, then overwrite it.",
            },
        )
        self.assertIn("Do not mutate", changed["hookSpecificOutput"]["additionalContext"])
        denied = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={**self.common, "tool_name": "Write", "tool_input": {"file_path": str(self.project / "foo.py")}},
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

    def critic_output(self, packet_hash: str) -> str:
        receipt = {
            "schema_version": 1,
            "packet_hash": packet_hash,
            "verdict": "PASS",
            "reviewed_sections": ["task_profile", "replan_provenance", "original_request", "context_manifest", "goal", "intake", "territory_discovery", "unknowns", "options", "acceptance_criteria", "plan", "mutation_scope"],
            "blocking_findings": [],
            "high_findings": [],
            "context_contamination": [],
        }
        return "Verdict: PASS\nMYTHOS_CRITIC_RECEIPT_V1_BEGIN\n" + json.dumps(receipt) + "\nMYTHOS_CRITIC_RECEIPT_V1_END"

    def test_real_claude_named_agent_event_schema_can_pass(self) -> None:
        _, packet_hash = self.seal_review()
        self.assertEqual(self.record_reviewer_launch("mythos-plan-critic", host="claude"), {})
        agent_id = "claude-critic-1"
        started = handle_hook(
            host="claude",
            event="SubagentStart",
            payload={**self.common, "agent_id": agent_id, "agent_type": "mythos-plan-critic"},
        )
        self.assertIn("Host-observed context isolation is verified", started["hookSpecificOutput"]["additionalContext"])
        accepted = handle_hook(
            host="claude",
            event="SubagentStop",
            payload={
                **self.common,
                "agent_id": agent_id,
                "agent_type": "mythos-plan-critic",
                "agent_transcript_path": self.agent_transcript(agent_id),
                "last_assistant_message": self.critic_output(packet_hash),
            },
        )
        self.assertEqual(accepted, {})
        state = RuntimeStore(self.project, self.run_id, root=self.state_root).load()
        self.assertEqual(state["evidence"]["pending_review_packet"]["review_result"], "PASS")

    def test_claude_reviewer_requires_distinct_nested_transcript(self) -> None:
        _, packet_hash = self.seal_review()
        self.assertEqual(self.record_reviewer_launch("mythos-plan-critic", host="claude"), {})
        agent_id = "claude-critic-bad-transcript"
        handle_hook(
            host="claude",
            event="SubagentStart",
            payload={**self.common, "agent_id": agent_id, "agent_type": "mythos-plan-critic"},
        )
        rejected = handle_hook(
            host="claude",
            event="SubagentStop",
            payload={
                **self.common,
                "agent_id": agent_id,
                "agent_type": "mythos-plan-critic",
                "agent_transcript_path": self.common["transcript_path"],
                "last_assistant_message": self.critic_output(packet_hash),
            },
        )
        self.assertEqual(rejected["decision"], "block")
        self.assertIn("host-verified fresh start", rejected["reason"])

    def test_codex_reviewer_requires_observable_none_and_neutral_prompt(self) -> None:
        self.seal_review()
        missing_none = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={
                **self.common,
                "tool_name": "spawn_agent",
                "tool_input": {
                    "task_name": "mythos_plan_critic",
                    "message": REVIEWER_LAUNCH_PROMPT,
                },
            },
        )
        self.assertEqual(missing_none["hookSpecificOutput"]["permissionDecision"], "deny")
        persuasive = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={
                **self.common,
                "tool_name": "spawn_agent",
                "tool_input": {
                    "task_name": "mythos_plan_critic",
                    "message": "Please approve my plan because it is correct.",
                    "fork_turns": "none",
                },
            },
        )
        self.assertEqual(persuasive["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.record_reviewer_launch("mythos-plan-critic"), {})

    def test_observable_launch_intent_is_mandatory_for_critic_pass(self) -> None:
        packet, packet_hash = self.seal_review()
        started = handle_hook(
            host="codex",
            event="SubagentStart",
            payload={**self.common, "agent_id": "critic-contaminated", "agent_type": "mythos-plan-critic"},
        )
        self.assertIn("NOT verified", started["hookSpecificOutput"]["additionalContext"])
        receipt = {
            "schema_version": 1,
            "packet_hash": packet_hash,
            "verdict": "PASS",
            "reviewed_sections": ["task_profile", "replan_provenance", "original_request", "context_manifest", "goal", "intake", "territory_discovery", "unknowns", "options", "acceptance_criteria", "plan", "mutation_scope"],
            "blocking_findings": [],
            "high_findings": [],
            "context_contamination": [],
        }
        rejected = handle_hook(
            host="codex",
            event="SubagentStop",
            payload={
                **self.common,
                "agent_id": "critic-contaminated",
                "agent_type": "mythos-plan-critic",
                "last_assistant_message": "Verdict: PASS\nMYTHOS_CRITIC_RECEIPT_V1_BEGIN\n" + json.dumps(receipt) + "\nMYTHOS_CRITIC_RECEIPT_V1_END",
            },
        )
        self.assertEqual(rejected["decision"], "block")
        second = handle_hook(
            host="codex",
            event="SubagentStart",
            payload={**self.common, "agent_id": "critic-contaminated-overwrite", "agent_type": "mythos-plan-critic", "fork_turns": "none"},
        )
        self.assertIn("no active hook-sealed plan critic packet", second["hookSpecificOutput"]["additionalContext"])
        result = self.stop_with(
            "MYTHOS_APPROVAL_BUNDLE_V1_BEGIN",
            self.approval_bundle(packet, packet_hash),
            "MYTHOS_APPROVAL_BUNDLE_V1_END",
        )
        self.assertIn("no accepted terminal PASS", result["reason"])
    def test_plan_only_completes_without_attempts_or_content_delta(self) -> None:
        packet = self.review_packet()
        packet["task_profile"] = "plan_only"
        packet["goal"] = "Produce an approved implementation plan only"
        packet["plan"][0]["surfaces"] = []
        packet["plan"][0]["action"] = "Deliver the approved plan without implementation"
        packet["plan"][0]["rollback"] = "No mutation to roll back"
        packet["mutation_scope"] = {"paths": [], "commands": [], "external_effects": []}
        _, approval_hash = self.approve(packet)
        denied = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={**self.common, "tool_name": "Write", "tool_input": {"file_path": str(self.project / "foo.py")}},
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        verification = {
            "schema_version": 1,
            "run_id": self.run_id,
            "approval_bundle_hash": approval_hash,
            "implementation_notes": {"summary": "Plan delivered; no implementation performed"},
            "increment_evidence": [],
            "acceptance_evidence": [{"criterion": "AC-1", "evidence": "approved plan packet", "result": "PASS"}],
            "reconciliation": {"deviations": [{
                "subject_type": "PLAN_STEP", "subject_id": "P-1", "classification": "MATCH",
                "evidence": "plan-only step completed without mutation",
            }]},
        }
        packet_hash = self.seal_verification(verification)
        self.pass_verifier(packet_hash, agent_id="verifier-plan-only")
        result = self.stop_with(
            "MYTHOS_COMPLETION_BUNDLE_V1_BEGIN",
            self.completion(verification, packet_hash),
            "MYTHOS_COMPLETION_BUNDLE_V1_END",
        )
        self.assertEqual(result, {})
        state = RuntimeStore(self.project, self.run_id, root=self.state_root).load()
        self.assertEqual(state["phase"], Phase.DONE.value)
        self.assertEqual(state["attempts"], [])
        sealed = state["evidence"]["pending_verification_packet"]["packet"]
        self.assertEqual(sealed["content_delta"], [])

    def test_three_no_gain_attempts_force_hard_stop_and_terminal_packet(self) -> None:
        _, approval_hash = self.approve()
        for index in range(1, 4):
            self.authorize_step()
            attempt = {
                "schema_version": 1,
                "run_id": self.run_id,
                "approval_bundle_hash": approval_hash,
                "step": "P-1",
                "hypothesis": f"Distinct hypothesis {index}",
                "action": f"Distinct bounded observation {index}",
                "evidence_snapshot": f"No evidence gain in observation {index}",
                "outcome": "FAIL",
                "evidence_gain": False,
            }
            result = self.stop_with(
                "MYTHOS_ATTEMPT_PACKET_V1_BEGIN", attempt, "MYTHOS_ATTEMPT_PACKET_V1_END"
            )
        self.assertIn("Three consecutive", result["reason"])
        denied = handle_hook(
            host="codex",
            event="PreToolUse",
            payload={**self.common, "tool_name": "Write", "tool_input": {"file_path": str(self.project / "foo.py")}},
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        terminal = {
            "schema_version": 1,
            "run_id": self.run_id,
            "terminal_state": "NEEDS_HUMAN_JUDGMENT",
            "current_phase": "IMPLEMENTATION_LOOP",
            "reason": "Three distinct hypotheses produced no evidence gain",
            "evidence": {"attempt_count": 3},
            "resume_condition": "Human supplies a new constraint or observation",
        }
        stopped = self.stop_with(
            "MYTHOS_TERMINAL_PACKET_V1_BEGIN", terminal, "MYTHOS_TERMINAL_PACKET_V1_END"
        )
        self.assertIn("Resume condition", stopped["systemMessage"])
        state = RuntimeStore(self.project, self.run_id, root=self.state_root).load()
        self.assertEqual(state["terminal_state"], "NEEDS_HUMAN_JUDGMENT")
        self.assertEqual(state["resume_condition"], terminal["resume_condition"])
    def test_explicit_non_success_terminal_state_can_stop(self) -> None:
        store = RuntimeStore(self.project, self.run_id, root=self.state_root)
        store.set_terminal(
            session_id=self.common["session_id"],
            terminal_state=TerminalState.BLOCKED,
            reason="External dependency unavailable",
        )
        stopped = handle_hook(
            host="codex",
            event="Stop",
            payload={**self.common, "last_assistant_message": "Blocked with evidence."},
        )
        self.assertIn("systemMessage", stopped)

    def test_state_root_inside_project_and_extra_packet_fields_are_rejected(self) -> None:
        packet = self.review_packet()
        packet["unexpected"] = "not allowed"
        result = self.stop_with("MYTHOS_REVIEW_PACKET_V1_BEGIN", packet, "MYTHOS_REVIEW_PACKET_V1_END")
        self.assertIn("unsupported fields", result["reason"])

        prior = os.environ["MYTHOS5_STATE_HOME"]
        os.environ["MYTHOS5_STATE_HOME"] = str(self.project / ".mythos-state")
        try:
            rejected = handle_hook(
                host="codex",
                event="SessionStart",
                payload={"session_id": "inside-state", "cwd": str(self.project)},
            )
        finally:
            os.environ["MYTHOS5_STATE_HOME"] = prior
        self.assertIn("hookSpecificOutput", rejected)
        self.assertIn("outside the governed project", rejected["hookSpecificOutput"]["additionalContext"])

if __name__ == "__main__":
    unittest.main()



