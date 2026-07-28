from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from cofer_u_pass.config.settings import AppConfig, restrict_private_path
from cofer_u_pass.domain.models import ProviderModel

_PROFILE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class ModelCatalogSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0"
    profile_id: str
    provider: str
    models: list[ProviderModel] = Field(default_factory=list)
    updated_at: datetime


class ModelCatalogStore:
    """Derived, rebuildable model catalog stored outside authoritative SQLite state."""

    def __init__(self, config: AppConfig):
        self.root = (config.data_path / "model-catalog").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        restrict_private_path(self.root, directory=True)

    def _path(self, profile_id: str) -> Path:
        if not _PROFILE_RE.fullmatch(profile_id):
            raise ValueError("invalid profile id for model catalog")
        return self.root / f"{profile_id}.json"

    def load(self, profile_id: str) -> ModelCatalogSnapshot | None:
        path = self._path(profile_id)
        if not path.exists():
            return None
        if path.is_symlink():
            raise RuntimeError("model catalog file must not be a symlink")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            snapshot = ModelCatalogSnapshot.model_validate(raw)
        except Exception as exc:
            raise RuntimeError(f"invalid model catalog for {profile_id}: {exc}") from exc
        if snapshot.profile_id != profile_id:
            raise RuntimeError("model catalog profile id mismatch")
        return snapshot

    def save(self, profile_id: str, provider: str, models: list[ProviderModel]) -> ModelCatalogSnapshot:
        path = self._path(profile_id)
        snapshot = ModelCatalogSnapshot(
            profile_id=profile_id,
            provider=provider,
            models=models,
            updated_at=datetime.now(timezone.utc),
        )
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        restrict_private_path(tmp, directory=False)
        tmp.replace(path)
        restrict_private_path(path, directory=False)
        return snapshot

    def clear(self, profile_id: str) -> None:
        path = self._path(profile_id)
        if path.exists() and not path.is_symlink():
            path.unlink()
