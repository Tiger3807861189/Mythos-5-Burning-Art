"""Portable advisory file locking for Windows, macOS, and Linux."""

from __future__ import annotations

import errno
import json
import os
import socket
import time
import uuid
from pathlib import Path
from typing import Callable

from .canonical import canonical_text


class LockTimeout(TimeoutError):
    pass


class FileLock:
    """A persistent-path OS advisory lock.

    The operating system owns the lock, so process termination releases it
    without any pathname takeover. The file is intentionally never unlinked:
    removing a lock pathname while another process can open it creates a race.
    ``stale_after`` remains accepted for backward compatibility but is not
    needed by this implementation.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        timeout: float = 10.0,
        stale_after: float = 60.0,
        poll_interval: float = 0.05,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self.stale_after = stale_after
        self.poll_interval = poll_interval
        self.clock = clock
        self.token = uuid.uuid4().hex
        self._descriptor: int | None = None
        self._held = False

    def _metadata(self) -> dict[str, object]:
        return {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "created_at": self.clock(),
            "token": self.token,
        }

    def _try_lock(self, descriptor: int) -> None:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            return
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(self, descriptor: int) -> None:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)

    def _write_metadata(self, descriptor: int) -> None:
        payload = canonical_text(self._metadata()).encode("utf-8")
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(descriptor, bytes([0]))
        os.lseek(descriptor, 1, os.SEEK_SET)
        os.ftruncate(descriptor, 1)
        os.write(descriptor, payload)
        os.fsync(descriptor)

    def _read(self) -> dict[str, object] | None:
        try:
            raw = self.path.read_bytes()
            if raw.startswith(b"\0"):
                raw = raw[1:]
            return json.loads(raw.decode("utf-8")) if raw else None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return None

    def acquire(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            descriptor: int | None = None
            try:
                descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"\0")
                    os.fsync(descriptor)
                self._try_lock(descriptor)
                self._write_metadata(descriptor)
                self._descriptor = descriptor
                self._held = True
                return self
            except OSError as error:
                if descriptor is not None:
                    os.close(descriptor)
                retryable = error.errno in {
                    errno.EACCES, errno.EAGAIN, errno.EDEADLK, errno.EPERM,
                } or isinstance(error, PermissionError)
                if not retryable:
                    raise
                if time.monotonic() >= deadline:
                    raise LockTimeout(f"Timed out waiting for lock: {self.path}") from error
                time.sleep(self.poll_interval)

    def release(self) -> None:
        descriptor = self._descriptor
        if not self._held or descriptor is None:
            return
        try:
            self._unlock(descriptor)
        finally:
            os.close(descriptor)
            self._descriptor = None
            self._held = False

    def __enter__(self) -> "FileLock":
        return self.acquire()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()