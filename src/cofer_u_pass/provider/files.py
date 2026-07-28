from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from pydantic import BaseModel, ConfigDict

from cofer_u_pass.config.settings import AppConfig


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ProviderFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    object: str = "file"
    bytes: int
    created_at: str
    filename: str
    purpose: str = "user_data"
    mime_type: str | None = None
    sha256: str


class ProviderFileStore:
    """Small local Files-API store used by the restricted provider surface.

    Browser artifacts remain in ArtifactStore. This store is the transport plane
    for files uploaded before a run and for exported artifacts that need stable
    OpenAI-style file IDs.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.root = config.provider_files_path
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_name(name: str) -> str:
        value = Path(name).name.replace("\x00", "").strip()
        return (value or "file.bin")[:240]

    def _dir(self, file_id: str) -> Path:
        if not file_id.startswith("file-") or not file_id[5:].replace("-", "").isalnum():
            raise KeyError(file_id)
        path = (self.root / file_id).resolve()
        if self.root.resolve() not in path.parents:
            raise KeyError(file_id)
        return path

    def _metadata_path(self, file_id: str) -> Path:
        return self._dir(file_id) / "metadata.json"

    def _content_path(self, file_id: str, metadata: ProviderFile | None = None) -> Path:
        meta = metadata or self.get(file_id)
        return self._dir(file_id) / meta.filename

    def put_stream(self, stream: BinaryIO, *, filename: str, purpose: str = "user_data") -> ProviderFile:
        file_id = "file-" + uuid.uuid4().hex
        directory = self._dir(file_id)
        directory.mkdir(parents=True, exist_ok=False)
        safe_name = self._safe_name(filename)
        target = directory / safe_name
        tmp = directory / ".upload.tmp"
        digest = hashlib.sha256()
        size = 0
        try:
            with tmp.open("wb") as dst:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.config.security.max_input_file_bytes:
                        raise ValueError("file exceeds max_input_file_bytes")
                    digest.update(chunk)
                    dst.write(chunk)
                dst.flush()
                os.fsync(dst.fileno())
            tmp.replace(target)
            meta = ProviderFile(
                id=file_id,
                bytes=size,
                created_at=_utc(),
                filename=safe_name,
                purpose=purpose or "user_data",
                mime_type=mimetypes.guess_type(safe_name)[0],
                sha256=digest.hexdigest(),
            )
            self._metadata_path(file_id).write_text(meta.model_dump_json(indent=2), encoding="utf-8")
            return meta
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def put_path(self, path: Path, *, filename: str | None = None, purpose: str = "user_data") -> ProviderFile:
        with path.open("rb") as stream:
            return self.put_stream(stream, filename=filename or path.name, purpose=purpose)

    def get(self, file_id: str) -> ProviderFile:
        path = self._metadata_path(file_id)
        if not path.is_file():
            raise KeyError(file_id)
        return ProviderFile.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def content_path(self, file_id: str) -> Path:
        meta = self.get(file_id)
        path = self._content_path(file_id, meta).resolve(strict=True)
        if self._dir(file_id).resolve() not in path.parents or not path.is_file() or path.is_symlink():
            raise KeyError(file_id)
        return path

    def delete(self, file_id: str) -> None:
        directory = self._dir(file_id)
        if not directory.exists():
            raise KeyError(file_id)
        shutil.rmtree(directory)
