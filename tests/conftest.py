from __future__ import annotations

from pathlib import Path

import pytest

from cofer_u_pass.config.settings import AppConfig, ensure_base_layout


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig.model_validate({
        "data_root": str(tmp_path / "data"),
        "browser": {"headless_default": True, "global_concurrency": 2, "action_timeout_seconds": 15, "response_stability_seconds": 0.5},
        "api": {"host": "127.0.0.1", "port": 8765, "token_file": "secrets/api-token", "cors_origins": []},
    })
    ensure_base_layout(cfg)
    cfg.api_token_path.write_text("test-token", encoding="utf-8")
    return cfg
