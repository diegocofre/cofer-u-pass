from pathlib import Path

import pytest
from pydantic import ValidationError

from cofer_u_pass.domain.models import ProtocolDefinition
from cofer_u_pass.protocols.loader import build_plan, load_protocol, validate_inputs


def test_example_protocol_builds_immutable_plan():
    root = Path(__file__).parents[2]
    protocol = load_protocol(root / "examples" / "ask.yaml")
    inputs = validate_inputs(protocol, {"prompt": "hello"})
    plan = build_plan(protocol, inputs, 30)
    assert plan.actions[1].inputs["text"] == "hello"
    assert plan.actions[1].external_effects == ["send_message"]
    with pytest.raises(ValidationError):
        plan.actions[0].type = "changed"


def test_input_schema_is_enforced():
    root = Path(__file__).parents[2]
    protocol = load_protocol(root / "examples" / "ask.yaml")
    with pytest.raises(Exception):
        validate_inputs(protocol, {})
