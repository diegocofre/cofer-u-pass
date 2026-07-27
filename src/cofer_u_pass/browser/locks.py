from __future__ import annotations

import os
from pathlib import Path
from typing import IO


class ProfileLockedError(RuntimeError):
    pass


class ProfileLock:
    """Cross-platform process lock stored inside the profile directory."""

    def __init__(self, profile_dir: Path):
        self.profile_dir = profile_dir
        self.path = profile_dir / ".cofer-u-pass.lock"
        self._file: IO[bytes] | None = None

    def acquire(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        f = self.path.open("a+b")
        # Windows byte-range locks are mandatory. Reading byte 0 before trying
        # to acquire the lock can therefore raise PermissionError while another
        # process legitimately owns the profile. Use file metadata instead; a
        # one-byte sentinel is sufficient for msvcrt.locking and is safe to
        # initialize before any process has acquired this previously-empty file.
        if os.fstat(f.fileno()).st_size == 0:
            f.seek(0)
            f.write(b"0")
            f.flush()
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            f.close()
            raise ProfileLockedError(str(self.profile_dir)) from exc
        self._file = f

    def release(self) -> None:
        f = self._file
        if not f:
            return
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()
            self._file = None

    def __enter__(self) -> "ProfileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
