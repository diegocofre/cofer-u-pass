from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from cofer_u_pass.domain.errors import ProtocolError
from cofer_u_pass.domain.models import ActionPlan, ExecutionPlan, ProtocolDefinition, RetryPolicy

INPUT_REF = re.compile(r"^\$\{input\.([A-Za-z0-9_.-]+)\}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_protocol(path: Path) -> ProtocolDefinition:
    path = path.expanduser().resolve(strict=True)
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(raw)
        elif suffix == ".json":
            data = json.loads(raw)
        elif suffix == ".toml":
            data = tomllib.loads(raw.decode("utf-8"))
        else:
            raise ProtocolError("protocol format must be .yaml, .yml, .json, or .toml")
        return ProtocolDefinition.model_validate(data)
    except ProtocolError:
        raise
    except Exception as exc:
        raise ProtocolError(f"invalid protocol {path}: {exc}") from exc


def validate_inputs(protocol: ProtocolDefinition, values: dict[str, Any]) -> dict[str, Any]:
    validator = Draft202012Validator(protocol.input_schema)
    errors = sorted(validator.iter_errors(values), key=lambda e: list(e.path))
    if errors:
        rendered = "; ".join(f"{'.'.join(map(str, e.path)) or '$'}: {e.message}" for e in errors[:10])
        raise ProtocolError(f"protocol input validation failed: {rendered}")
    return values


def _get_path(values: dict[str, Any], dotted: str) -> Any:
    cur: Any = values
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise ProtocolError(f"missing input reference: {dotted}")
        cur = cur[part]
    return cur


def resolve_input_refs(value: Any, inputs: dict[str, Any]) -> Any:
    if isinstance(value, str):
        match = INPUT_REF.match(value)
        if match:
            return _get_path(inputs, match.group(1))
        return value
    if isinstance(value, list):
        return [resolve_input_refs(v, inputs) for v in value]
    if isinstance(value, dict):
        return {k: resolve_input_refs(v, inputs) for k, v in value.items()}
    return value


_OPERATION_DEFAULTS: dict[str, dict[str, Any]] = {
    "open_conversation": {"success": "conversation recognized", "recovery": "reconcile page and conversation identity", "external": []},
    "configure_inference": {"success": "requested model and reasoning effort are visibly selected and verified", "recovery": "rediscover provider inference state and fail closed unless the requested state is proven", "external": []},
    "attach_files": {"success": "provider attachment state is visibly confirmed", "recovery": "do not repeat unless absence is proven", "external": ["upload_file"]},
    "send_message": {"success": "submitted user message is visibly confirmed", "recovery": "reconcile message identity before any retry", "external": ["send_message"]},
    "capture_response": {"success": "response reaches provider completion plus DOM stability", "recovery": "reopen conversation and reconcile last response", "external": []},
    "download_artifacts": {"success": "downloads are saved and hashed", "recovery": "reconcile artifact presence before repeating provider action", "external": ["download_artifact"]},
    "hook": {"success": "hook exits successfully and returns valid typed output", "recovery": "rerun only when hook contract marks operation safe", "external": []},
    "checkpoint": {"success": "safe checkpoint persisted", "recovery": "not applicable", "external": []},
    "finalize": {"success": "canonical result persisted", "recovery": "rebuild from persisted canonical state", "external": []},
}


def build_plan(protocol: ProtocolDefinition, inputs: dict[str, Any], default_timeout: float) -> ExecutionPlan:
    actions: list[ActionPlan] = []
    for index, op in enumerate(protocol.operations, start=1):
        defaults = _OPERATION_DEFAULTS[op.type]
        params = resolve_input_refs(op.params, inputs)
        actions.append(ActionPlan(
            action_id=f"a{index:04d}-{op.type}",
            type=op.type,
            inputs=params,
            preconditions=["run is active", "profile lock is held"],
            external_effects=defaults["external"],
            timeout_seconds=op.timeout_seconds or default_timeout,
            retry=RetryPolicy(max_attempts=op.retry_attempts or 2),
            success_condition=defaults["success"],
            recovery_strategy=defaults["recovery"],
            checkpoint_eligible=op.type not in {"hook", "attach_files"},
        ))
    if actions[-1].type != "finalize":
        actions.append(ActionPlan(
            action_id=f"a{len(actions)+1:04d}-finalize",
            type="finalize", inputs={}, preconditions=["run is active"], external_effects=[],
            timeout_seconds=default_timeout, retry=RetryPolicy(max_attempts=1),
            success_condition=_OPERATION_DEFAULTS["finalize"]["success"],
            recovery_strategy=_OPERATION_DEFAULTS["finalize"]["recovery"], checkpoint_eligible=True,
        ))
    return ExecutionPlan(actions=tuple(actions), required_capabilities=tuple(protocol.required_capabilities))
