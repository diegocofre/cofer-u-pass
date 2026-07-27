from __future__ import annotations

import builtins
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from cofer_u_pass.browser.locks import ProfileLock, ProfileLockedError


def test_lock_initializes_sentinel_without_reading_lock_file(tmp_path, monkeypatch):
    """Regression: Windows mandatory locks can reject reads of byte 0 while busy."""
    profile = tmp_path / "profile"
    profile.mkdir()
    lock_path = profile / ".cofer-u-pass.lock"
    lock_path.touch()

    original_open = Path.open

    class NoReadWrapper:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

        def read(self, *args, **kwargs):
            raise AssertionError("ProfileLock.acquire must not read before locking")

    def patched_open(self, *args, **kwargs):
        f = original_open(self, *args, **kwargs)
        if self == lock_path:
            return NoReadWrapper(f)
        return f

    monkeypatch.setattr(Path, "open", patched_open)
    lock = ProfileLock(profile)
    lock.acquire()
    try:
        assert lock_path.stat().st_size == 1
    finally:
        lock.release()


def test_busy_windows_lock_is_reported_as_profile_locked(tmp_path, monkeypatch):
    """Simulate msvcrt rejecting LK_NBLCK for a legitimately busy profile."""
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / ".cofer-u-pass.lock").write_bytes(b"0")

    import cofer_u_pass.browser.locks as locks_module

    monkeypatch.setattr(locks_module.os, "name", "nt")
    fake_msvcrt = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2)

    def locking(fd, mode, length):
        if mode == fake_msvcrt.LK_NBLCK:
            raise PermissionError(13, "Permission denied")

    fake_msvcrt.locking = locking
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    with pytest.raises(ProfileLockedError):
        ProfileLock(profile).acquire()
