"""Tamper-evident event logs and atomic JSON snapshots."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .canonical import canonical_text, digest
from .locking import FileLock


GENESIS_CHECKSUM = "0" * 64


class IntegrityError(RuntimeError):
    pass


def atomic_write_json(path: Path, value: Any, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_text(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            except OSError:
                pass
            finally:
                os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise IntegrityError(f"Invalid JSON in {path}: {error}") from error


class EventLog:
    def __init__(self, path: str | os.PathLike[str], *, lock_path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path)
        self.lock_path = Path(lock_path) if lock_path else self.path.with_suffix(self.path.suffix + ".lock")

    @staticmethod
    def _checksum_body(sequence: int, previous: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"sequence": sequence, "previous_checksum": previous, "payload": payload}

    def read_verified(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        previous = GENESIS_CHECKSUM
        expected_sequence = 1
        with self.path.open("r", encoding="utf-8", newline="") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.endswith("\n"):
                    raise IntegrityError(f"Truncated event record at line {line_number}")
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise IntegrityError(f"Invalid event JSON at line {line_number}") from error
                if record.get("sequence") != expected_sequence:
                    raise IntegrityError(f"Non-monotonic sequence at line {line_number}")
                if record.get("previous_checksum") != previous:
                    raise IntegrityError(f"Broken checksum chain at line {line_number}")
                body = self._checksum_body(expected_sequence, previous, record.get("payload"))
                expected_checksum = digest(body)
                if record.get("checksum") != expected_checksum:
                    raise IntegrityError(f"Checksum mismatch at line {line_number}")
                records.append(record)
                previous = expected_checksum
                expected_sequence += 1
        return records

    def append(self, payload: dict[str, Any]) -> dict[str, Any]:
        with FileLock(self.lock_path):
            return self.append_locked(payload)

    def append_locked(self, payload: dict[str, Any]) -> dict[str, Any]:
        records = self.read_verified()
        sequence = len(records) + 1
        previous = records[-1]["checksum"] if records else GENESIS_CHECKSUM
        body = self._checksum_body(sequence, previous, payload)
        record = {**body, "checksum": digest(body)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_text(record))
            stream.flush()
            os.fsync(stream.fileno())
        return record

