from __future__ import annotations

import os
import secrets
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_data_dir
from pydantic import BaseModel, ConfigDict, Field


class BrowserConfig(BaseModel):
    global_concurrency: int = Field(default=2, ge=1, le=16)
    headless_default: bool = False
    action_timeout_seconds: float = Field(default=90, gt=1, le=3600)
    response_stability_seconds: float = Field(default=1.5, ge=0.25, le=30)


class ApiConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    token_file: str = "secrets/api-token"
    cors_origins: list[str] = Field(default_factory=list)


class SecurityConfig(BaseModel):
    max_input_file_bytes: int = 100 * 1024 * 1024
    max_artifact_bytes: int = 500 * 1024 * 1024
    max_archive_entries: int = Field(default=1000, ge=1, le=100000)
    max_archive_uncompressed_bytes: int = Field(default=500 * 1024 * 1024, ge=1)
    max_archive_depth: int = Field(default=12, ge=1, le=128)
    max_combined_text_bytes: int = Field(default=8 * 1024 * 1024, ge=1024)
    max_inline_text_bytes: int = Field(default=64 * 1024, ge=1024)
    allowed_input_extensions: list[str] = Field(default_factory=list)
    allowed_artifact_extensions: list[str] = Field(default_factory=list)


class RetentionConfig(BaseModel):
    events_days: int = 30
    evidence_days: int = 30
    backups_days: int = 30
    artifacts_days: int = 90
    completed_runs_days: int = 90


class HookConfig(BaseModel):
    timeout_seconds: float = 60
    max_input_bytes: int = 2 * 1024 * 1024
    max_output_bytes: int = 2 * 1024 * 1024


class DoctorConfig(BaseModel):
    screenshots: bool = False
    dom_fragments: bool = True
    network_diagnostics: bool = False


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0"
    data_root: str
    temp_root: str | None = None
    log_level: str = "INFO"
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    hooks: HookConfig = Field(default_factory=HookConfig)
    doctor: DoctorConfig = Field(default_factory=DoctorConfig)

    @property
    def data_path(self) -> Path:
        return Path(self.data_root).expanduser().resolve()

    @property
    def temp_path(self) -> Path:
        return (Path(self.temp_root).expanduser() if self.temp_root else self.data_path / "tmp").resolve()

    @property
    def db_path(self) -> Path:
        return self.data_path / "cofer-u-pass.sqlite3"

    @property
    def profiles_path(self) -> Path:
        return self.data_path / "profiles"

    @property
    def artifacts_path(self) -> Path:
        return self.data_path / "artifacts"

    @property
    def provider_files_path(self) -> Path:
        return self.data_path / "provider-files"

    @property
    def evidence_path(self) -> Path:
        return self.data_path / "evidence"

    @property
    def backups_path(self) -> Path:
        return self.data_path / "backups"

    @property
    def logs_path(self) -> Path:
        return self.data_path / "logs"

    @property
    def secrets_path(self) -> Path:
        return self.data_path / "secrets"

    @property
    def api_token_path(self) -> Path:
        configured = Path(self.api.token_file)
        return configured if configured.is_absolute() else self.data_path / configured


def default_config_path() -> Path:
    override = os.environ.get("COFER_U_PASS_CONFIG")
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_config_dir("cofer-u-pass", "dc-sistemas")) / "config.toml"


def default_data_root() -> Path:
    override = os.environ.get("COFER_U_PASS_DATA_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_data_dir("cofer-u-pass", "dc-sistemas"))


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _env_overlay() -> dict[str, Any]:
    overlay: dict[str, Any] = {}
    mapping = {
        "COFER_U_PASS_DATA_ROOT": ("data_root", str),
        "COFER_U_PASS_LOG_LEVEL": ("log_level", str),
        "COFER_U_PASS_API_PORT": ("api.port", int),
        "COFER_U_PASS_BROWSER_CONCURRENCY": ("browser.global_concurrency", int),
        "COFER_U_PASS_HEADLESS": ("browser.headless_default", lambda v: v.lower() in {"1", "true", "yes", "on"}),
    }
    for env, (path, cast) in mapping.items():
        if env not in os.environ:
            continue
        value = cast(os.environ[env])
        cur = overlay
        parts = path.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value
    return overlay


def load_config(*, explicit: dict[str, Any] | None = None, config_path: Path | None = None) -> AppConfig:
    base: dict[str, Any] = {"data_root": str(default_data_root())}
    path = config_path or default_config_path()
    if path.exists():
        with path.open("rb") as f:
            base = _deep_merge(base, tomllib.load(f))
    base = _deep_merge(base, _env_overlay())
    if explicit:
        base = _deep_merge(base, explicit)
    cfg = AppConfig.model_validate(base)
    if cfg.api.host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("v1 API binding is restricted to loopback")
    return cfg


def _toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_default_toml(config: AppConfig) -> str:
    return f'''schema_version = "1.0"
data_root = {_toml_quote(str(config.data_path))}
log_level = "INFO"

[browser]
global_concurrency = 2
headless_default = false
action_timeout_seconds = 90.0
response_stability_seconds = 1.5

[api]
host = "127.0.0.1"
port = 8765
token_file = "secrets/api-token"
cors_origins = []

[security]
max_input_file_bytes = 104857600
max_artifact_bytes = 524288000
max_archive_entries = 1000
max_archive_uncompressed_bytes = 524288000
max_archive_depth = 12
max_combined_text_bytes = 8388608
max_inline_text_bytes = 65536
allowed_input_extensions = []
allowed_artifact_extensions = []

[retention]
events_days = 30
evidence_days = 30
backups_days = 30
artifacts_days = 90
completed_runs_days = 90

[hooks]
timeout_seconds = 60.0
max_input_bytes = 2097152
max_output_bytes = 2097152

[doctor]
screenshots = false
dom_fragments = true
network_diagnostics = false
'''


def restrict_private_path(path: Path, *, directory: bool) -> None:
    if os.name != "nt":
        path.chmod(0o700 if directory else 0o600)
        return
    try:
        who = subprocess.check_output(["whoami"], text=True, encoding="utf-8", errors="replace").strip()
        if not who:
            raise RuntimeError("whoami returned an empty identity")
        grant = f"{who}:(OI)(CI)F" if directory else f"{who}:F"
        proc = subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", grant],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "icacls failed")
    except Exception as exc:
        raise RuntimeError(f"could not apply restrictive Windows ACL to {path}: {exc}") from exc


def ensure_base_layout(config: AppConfig) -> None:
    for path in [
        config.data_path, config.temp_path, config.profiles_path, config.artifacts_path,
        config.provider_files_path, config.evidence_path, config.backups_path, config.logs_path, config.secrets_path,
    ]:
        path.mkdir(parents=True, exist_ok=True)
        restrict_private_path(path, directory=True)


def setup_files(*, dry_run: bool = False) -> dict[str, str]:
    path = default_config_path()
    cfg = load_config(config_path=path)
    changes: dict[str, str] = {}
    if not path.exists():
        changes["config"] = str(path)
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_default_toml(cfg), encoding="utf-8")
    if not dry_run:
        ensure_base_layout(cfg)
    token_path = cfg.api_token_path
    if not token_path.exists():
        changes["api_token"] = str(token_path)
        if not dry_run:
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
            restrict_private_path(token_path, directory=False)
    return changes


def sanitized_snapshot(config: AppConfig) -> dict[str, Any]:
    data = config.model_dump(mode="json")
    data["api"]["token_file"] = str(config.api_token_path)
    return data


def rotate_api_token(config: AppConfig) -> Path:
    token_path = config.api_token_path
    token_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = token_path.with_name(token_path.name + ".new")
    tmp.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    restrict_private_path(tmp, directory=False)
    tmp.replace(token_path)
    return token_path
