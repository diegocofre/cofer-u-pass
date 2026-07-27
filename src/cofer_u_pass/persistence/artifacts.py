from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import uuid
from pathlib import Path

from cofer_u_pass.config.settings import AppConfig
from cofer_u_pass.domain.models import ArtifactRef


class ArtifactStore:
    def __init__(self, config: AppConfig):
        self.config = config

    def _safe_name(self, name: str) -> str:
        value = Path(name).name.replace("\x00", "").strip()
        if not value or value in {".", ".."}:
            return "artifact.bin"
        return value[:240]

    def _validate_extension(self, path: Path, allowed: list[str]) -> None:
        if not allowed:
            return
        ext = path.suffix.lower().lstrip(".")
        normalized = {x.lower().lstrip(".") for x in allowed}
        if ext not in normalized:
            raise ValueError(f"file extension .{ext} is not allowed")

    def validate_input(self, path: Path) -> Path:
        candidate = path.expanduser()
        if candidate.is_symlink():
            raise ValueError(f"input must be a regular non-symlink file: {candidate}")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError(f"input must be a regular non-symlink file: {resolved}")
        if resolved.stat().st_size > self.config.security.max_input_file_bytes:
            raise ValueError(f"input exceeds max_input_file_bytes: {resolved}")
        self._validate_extension(resolved, self.config.security.allowed_input_extensions)
        return resolved

    def ingest(self, source: Path, *, run_id: str, action_id: str, original_source: str | None = None) -> ArtifactRef:
        source = source.resolve(strict=True)
        if source.stat().st_size > self.config.security.max_artifact_bytes:
            raise ValueError("artifact exceeds max_artifact_bytes")
        self._validate_extension(source, self.config.security.allowed_artifact_extensions)
        run_dir = (self.config.artifacts_path / run_id).resolve()
        root = self.config.artifacts_path.resolve()
        if root not in run_dir.parents and run_dir != root:
            raise ValueError("artifact path escape")
        run_dir.mkdir(parents=True, exist_ok=True)
        name = self._safe_name(source.name)
        artifact_id = str(uuid.uuid4())
        target = run_dir / f"{artifact_id}-{name}"
        tmp = run_dir / f".{artifact_id}.tmp"
        with source.open("rb") as src, tmp.open("wb") as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        tmp.replace(target)
        digest = hashlib.sha256()
        with target.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return ArtifactRef(
            artifact_id=artifact_id, run_id=run_id, action_id=action_id, filename=name,
            path=str(target), sha256=digest.hexdigest(), size=target.stat().st_size,
            mime_type=mimetypes.guess_type(name)[0], source=original_source,
        )
