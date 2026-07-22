"""Hook-owned human approval receipts.

Filesystem permissions and the HMAC detect accidental or opportunistic
tampering. They are not a security boundary against code running as the same
operating-system user. Host sandboxing must provide that boundary.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import canonical_json, digest
from .locking import FileLock
from .paths import prepare_private_directory
from .storage import EventLog, IntegrityError, atomic_write_json, read_json


_OBSERVATION_SEAL = object()
SUPPORTED_HUMAN_EVENTS = {
    "claude": {"UserPromptSubmit"},
    "codex": {"UserPromptSubmit"},
}


def approval_syntax(run_id: str, bundle_hash: str) -> str:
    return f"APPROVE MYTHOS RUN {run_id} BUNDLE {bundle_hash}"


@dataclass(frozen=True)
class HookObservation:
    host: str
    event_name: str
    event_id: str
    session_id: str
    message: str
    _seal: object


def observe_human_event(*, host: str, event_name: str, payload: dict[str, Any]) -> HookObservation:
    """Validate a host hook payload and seal it for approval creation."""

    if event_name not in SUPPORTED_HUMAN_EVENTS.get(host, set()):
        raise ValueError(f"{host}:{event_name} is not an observable human approval event")
    actor = payload.get("actor_type", payload.get("actor", "human"))
    if actor != "human":
        raise ValueError("Approval must come from a human-authored event")
    message = payload.get("prompt", payload.get("message"))
    session_id = payload.get("session_id")
    event_id = payload.get("event_id", payload.get("uuid", payload.get("turn_id")))
    if not event_id and isinstance(message, str) and isinstance(session_id, str):
        event_id = "derived-" + digest(
            {
                "host": host,
                "event_name": event_name,
                "session_id": session_id,
                "message": message,
                "transcript_path": payload.get("transcript_path"),
            }
        )
    if not all(isinstance(value, str) and value for value in (message, session_id, event_id)):
        raise ValueError("Human event requires message, session_id, and an event identifier")
    return HookObservation(host, event_name, event_id, session_id, message, _OBSERVATION_SEAL)


class AuthorityStore:
    def __init__(self, paths: dict[str, Path]) -> None:
        self.paths = paths
        prepare_private_directory(paths["authority"])
        self.log = EventLog(paths["authority_log"])
        self.lock = paths["authority"] / "authority.lock"

    def _key(self) -> bytes:
        path = self.paths["authority_key"]
        prepare_private_directory(path.parent)
        with FileLock(path.with_name(path.name + ".lock")):
            if path.exists():
                key = path.read_bytes()
                if len(key) != 32:
                    raise IntegrityError("Authority key is malformed")
                return key
            key = secrets.token_bytes(32)
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(key)
                stream.flush()
                os.fsync(stream.fileno())
            return key
    def _signature(self, receipt: dict[str, Any]) -> str:
        return hmac.new(self._key(), canonical_json(receipt), hashlib.sha256).hexdigest()

    def create(
        self,
        *,
        observation: HookObservation,
        run_id: str,
        project: dict[str, Any],
        material: dict[str, Any],
        scope: Any,
    ) -> dict[str, Any]:
        if observation._seal is not _OBSERVATION_SEAL:
            raise PermissionError("Approval creation requires a sealed hook observation")
        expected = approval_syntax(run_id, str(material["bundle_hash"]))
        if observation.message != expected:
            raise ValueError(f"Approval text must exactly equal: {expected}")
        receipt = {
            "schema_version": "1",
            "run_id": run_id,
            "session_id": observation.session_id,
            "project": project,
            "material": material,
            "scope": scope,
            "human_event": {
                "host": observation.host,
                "event_name": observation.event_name,
                "event_id": observation.event_id,
                "message_hash": digest(observation.message),
            },
        }
        document = {"receipt": receipt, "signature": self._signature(receipt)}
        with FileLock(self.lock):
            self.log.append({"operation": "approval_created", "receipt_hash": digest(receipt)})
            atomic_write_json(self.paths["approval"], document)
        return document

    def validate(
        self,
        *,
        run_id: str,
        session_id: str,
        project: dict[str, Any],
        material: dict[str, Any],
    ) -> tuple[bool, list[str], dict[str, Any] | None]:
        path = self.paths["approval"]
        if not path.exists():
            return False, ["approval is missing"], None
        try:
            document = read_json(path)
            receipt = document["receipt"]
            signature = document["signature"]
        except (IntegrityError, KeyError, TypeError):
            return False, ["approval document is malformed"], None
        reasons: list[str] = []
        if not hmac.compare_digest(str(signature), self._signature(receipt)):
            reasons.append("approval signature is invalid")
        if receipt.get("run_id") != run_id:
            reasons.append("approval belongs to another run")
        if receipt.get("session_id") != session_id:
            reasons.append("approval belongs to another session")
        if receipt.get("project") != project:
            reasons.append("repository or worktree identity changed")
        prior = receipt.get("material", {})
        for key in ("base_fingerprint", "plan_hash", "scope_hash", "acceptance_hash", "critic_hash", "bundle_hash"):
            if prior.get(key) != material.get(key):
                reasons.append(f"{key} changed")
        return not reasons, reasons, receipt

    def invalidate(self, reasons: list[str]) -> None:
        with FileLock(self.lock):
            if self.paths["approval"].exists():
                self.log.append({"operation": "approval_invalidated", "reasons": reasons})
                self.paths["approval"].unlink(missing_ok=True)