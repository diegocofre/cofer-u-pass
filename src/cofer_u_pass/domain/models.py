from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CONTRACT_VERSION = "1.0"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    AUTHENTICATION_REQUIRED = "authentication_required"
    RECOVERABLE = "recoverable"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


class ActionState(StrEnum):
    PLANNED = "planned"
    STARTED = "started"
    CONFIRMED = "confirmed"
    RETRYABLE_FAILED = "retryable_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    OUTCOME_UNKNOWN = "outcome_unknown"


class FailureClass(StrEnum):
    TRANSIENT = "transient"
    AUTHENTICATION = "authentication"
    ADAPTER_MISMATCH = "adapter_mismatch"
    PROTOCOL_ERROR = "protocol_error"
    ENVIRONMENT = "environment"
    OUTCOME_UNKNOWN = "outcome_unknown"
    FATAL = "fatal"


class ConversationMode(StrEnum):
    NEW = "new"
    CONTINUE = "continue"
    IMPORTED = "imported"


def _non_empty_trimmed(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


class ProviderModel(BaseModel):
    """Provider-neutral model advertised by an authenticated web profile."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=200)
    supported_efforts: list[str] = Field(default_factory=list)
    native_id: str | None = None
    native_label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return _non_empty_trimmed(value, field_name="model id")

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return _non_empty_trimmed(value, field_name="provider").lower()

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        return _non_empty_trimmed(value, field_name="display_name")

    @field_validator("supported_efforts")
    @classmethod
    def normalize_efforts(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in values:
            value = _non_empty_trimmed(str(raw), field_name="supported effort").lower()
            if value not in normalized:
                normalized.append(value)
        return normalized


class InferenceSelection(BaseModel):
    """Public inference request after provider/profile routing is resolved."""

    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=160)
    effort: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        return _non_empty_trimmed(value, field_name="model")

    @field_validator("effort")
    @classmethod
    def normalize_effort(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _non_empty_trimmed(value, field_name="effort").lower()


class InferenceState(BaseModel):
    """Verified provider inference state expressed in public and native terms."""

    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=160)
    effort: str | None = None
    native_model: str | None = None
    native_effort: str | None = None
    verified: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResolvedInferenceTarget(BaseModel):
    """Internal route from a public model request to an authenticated profile."""

    model_config = ConfigDict(extra="forbid")
    provider: str
    profile_id: str
    selection: InferenceSelection
    model: ProviderModel | None = None
    legacy_profile_alias: bool = False


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[
        "document", "paragraph", "heading", "text", "code", "list", "list_item",
        "blockquote", "link", "image", "table", "thematic_break", "unknown"
    ]
    text: str | None = None
    level: int | None = None
    language: str | None = None
    href: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    children: list["Block"] = Field(default_factory=list)


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: str
    run_id: str
    action_id: str
    filename: str
    path: str
    sha256: str
    size: int
    mime_type: str | None = None
    source: str | None = None


class CanonicalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: str = CONTRACT_VERSION
    run_id: str
    blocks: Block
    markdown: str
    text: str
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    provider: str
    profile_id: str
    conversation_id: str | None = None
    completion: str = "completed"
    warnings: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: str = CONTRACT_VERSION
    run_id: str
    event_id: str
    sequence: int
    timestamp: datetime
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=2, ge=1, le=10)
    base_delay_seconds: float = Field(default=0.5, ge=0, le=30)


class ActionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action_id: str
    type: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    preconditions: list[str] = Field(default_factory=list)
    external_effects: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=90.0, gt=0, le=3600)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    success_condition: str
    recovery_strategy: str
    checkpoint_eligible: bool = True


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    plan_version: str = CONTRACT_VERSION
    actions: tuple[ActionPlan, ...]
    required_capabilities: tuple[str, ...] = ()


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    protocol_id: str
    protocol_version: str
    protocol_hash: str
    input_values: dict[str, Any]
    input_hash: str
    profile_id: str
    provider: str
    conversation_mode: ConversationMode
    conversation_id: str | None = None
    client_request_id: str | None = None
    config_hash: str
    config_snapshot: dict[str, Any]
    component_versions: dict[str, str]
    state: RunState
    plan: ExecutionPlan
    created_at: datetime
    updated_at: datetime
    error_class: FailureClass | None = None
    error_message: str | None = None


class ProfileRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: str
    provider: str
    profile_dir: str
    status: str = "created"
    authenticated: bool = False
    chromium_version: str | None = None
    created_at: datetime
    updated_at: datetime


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkpoint_id: str
    run_id: str
    action_id: str
    conversation_id: str | None = None
    current_url: str | None = None
    logical_state: dict[str, Any] = Field(default_factory=dict)
    component_versions: dict[str, str]
    protocol_hash: str
    input_hash: str
    artifact_ids: list[str] = Field(default_factory=list)
    blocks: Block | None = None
    next_action_id: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class ProtocolOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[
        "open_conversation", "configure_inference", "attach_files", "send_message", "capture_response",
        "download_artifacts", "hook", "checkpoint", "finalize"
    ]
    params: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float | None = Field(default=None, gt=0, le=3600)
    retry_attempts: int | None = Field(default=None, ge=1, le=10)


class ProtocolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    version: str = Field(min_length=1, max_length=64)
    engine_contract: str = CONTRACT_VERSION
    required_capabilities: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    operations: list[ProtocolOperation] = Field(min_length=1)
    output_contract: dict[str, Any] = Field(default_factory=dict)

    @field_validator("engine_contract")
    @classmethod
    def validate_contract(cls, value: str) -> str:
        if value.split(".")[0] != CONTRACT_VERSION.split(".")[0]:
            raise ValueError(f"unsupported engine contract {value}; expected {CONTRACT_VERSION}")
        return value


VALID_RUN_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.QUEUED: {RunState.RUNNING, RunState.CANCELLING, RunState.CANCELLED, RunState.FAILED},
    RunState.RUNNING: {
        RunState.COMPLETED, RunState.AUTHENTICATION_REQUIRED, RunState.RECOVERABLE,
        RunState.CANCELLING, RunState.FAILED, RunState.OUTCOME_UNKNOWN,
    },
    RunState.AUTHENTICATION_REQUIRED: {RunState.QUEUED, RunState.CANCELLING, RunState.CANCELLED, RunState.FAILED},
    RunState.RECOVERABLE: {RunState.QUEUED, RunState.CANCELLING, RunState.CANCELLED, RunState.FAILED, RunState.OUTCOME_UNKNOWN},
    RunState.CANCELLING: {RunState.CANCELLED, RunState.RECOVERABLE, RunState.OUTCOME_UNKNOWN, RunState.FAILED},
    RunState.CANCELLED: set(),
    RunState.COMPLETED: set(),
    RunState.FAILED: set(),
    RunState.OUTCOME_UNKNOWN: {RunState.QUEUED, RunState.CANCELLED, RunState.FAILED},
}


def assert_run_transition(current: RunState, target: RunState) -> None:
    if target not in VALID_RUN_TRANSITIONS[current]:
        raise ValueError(f"invalid run transition: {current.value} -> {target.value}")
